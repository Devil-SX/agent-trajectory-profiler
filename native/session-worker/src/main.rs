//! Internal JSONL protocol. Native source is retained verbatim, independent of
//! upstream IR evolution. Resource estimates are never exposed as measured usage.
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::io::{self, BufRead, Write};
use std::path::Path;
use std::time::UNIX_EPOCH;

const SCHEMA: &str = "trajectory.agent-session/1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    #[serde(rename = "id")]
    _id: Value,
    op: String,
    #[serde(default)]
    source_id: String,
    #[serde(default)]
    agent: String,
    #[serde(default)]
    content: String,
    #[serde(default)]
    source_path: String,
    #[serde(default)]
    input_file: Option<String>,
}

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn parse(request: &Request) -> Result<Value, String> {
    if request.op == "health" {
        return Ok(
            json!({"schema": SCHEMA, "worker_version":env!("CARGO_PKG_VERSION"), "parser": {"name":"agent-session", "version":"0.5.17"}}),
        );
    }
    if request.op != "parse" {
        return Err("unsupported operation".into());
    }
    if request.source_id.is_empty() {
        return Err("source_id is required".into());
    }
    if !["codex", "claude", "gemini", "cursor", "codebuddy", "pi"].contains(&request.agent.as_str())
    {
        return Err("unsupported agent".into());
    }
    // JSONL appends can stop in the middle of an encoded Unicode character or
    // JSON record. Decode only complete records; pending bytes remain archived.
    let file_content = request
        .input_file
        .as_ref()
        .map(std::fs::read)
        .transpose()
        .map_err(|_| "cannot read internal input_file")?;
    if file_content.is_some() && !request.content.is_empty() {
        return Err("content and input_file are mutually exclusive".into());
    }
    let source = file_content
        .as_deref()
        .unwrap_or(request.content.as_bytes());
    let is_document = request.agent == "gemini";
    let complete_bytes = if is_document || source.ends_with(b"\n") {
        source.len()
    } else {
        source
            .iter()
            .rposition(|byte| *byte == b'\n')
            .map_or(0, |i| i + 1)
    };
    let content = std::str::from_utf8(&source[..complete_bytes])
        .map_err(|_| "invalid UTF-8 in complete source records")?;
    let mut records = Vec::new();
    let mut valid_source = String::new();
    let mut values = Vec::new();
    let mut quarantined = Vec::new();
    let mut offset = 0;
    if is_document {
        let record: Value =
            serde_json::from_str(content).map_err(|_| "invalid source JSON document")?;
        records.push(json!({"ordinal":0,"byte_start":0,"byte_end":complete_bytes,
            "event_id": digest(format!("{}:0:{}",request.source_id,content).as_bytes()),
            "record_sha256":digest(content.as_bytes()),"record_type":"document", "session_id":record.get("sessionId")}));
    } else {
        for (ordinal, line) in content.split_inclusive('\n').enumerate() {
            let end = offset + line.len();
            if !line.trim().is_empty() {
                let record: Value = match serde_json::from_str::<Value>(line) {
                    Ok(record) if record.is_object() => record,
                    _ => {
                        quarantined.push(json!({"source_line":ordinal+1,"byte_start":offset,
                            "byte_end":end,"record_sha256":digest(line.as_bytes()),
                            "reason":"invalid_json_record"}));
                        // Keep a blank line in the parser view, never rewrite the archive or offsets.
                        valid_source.push('\n');
                        offset = end;
                        continue;
                    }
                };
                valid_source.push_str(line);
                values.push(record.clone());
                let payload = record.get("payload").unwrap_or(&record);
                let ts_ms = record
                    .get("timestamp")
                    .and_then(Value::as_str)
                    .and_then(|ts| chrono::DateTime::parse_from_rfc3339(ts).ok())
                    .map(|ts| ts.timestamp_millis());
                let lineage = if record.get("type").and_then(Value::as_str) == Some("session_meta")
                {
                    json!({"id":payload.get("id"),"forked_from_id":payload.get("forked_from_id"),"parent_thread_id":payload.get("parent_thread_id"),"source":payload.get("source")})
                } else if request.agent == "pi" {
                    json!({"id":record.get("id"),"parentId":record.get("parentId"),
                        "parentSession":record.get("parentSession"),"parent_session_id":record.get("parent_session_id")})
                } else {
                    Value::Null
                };
                records.push(json!({"ordinal":ordinal,"source_line":ordinal+1,"byte_start":offset,"byte_end":end,
                    "event_id":digest(format!("{}:{}:{}",request.source_id,ordinal,line).as_bytes()),
                    "record_sha256":digest(line.trim_end_matches(['\r','\n']).as_bytes()),
                    "record_type":record.get("type"),"payload_type":payload.get("type"),
                    "native_id":payload.get("id").or_else(||record.get("uuid")),
                    "parent_native_id":record.get("parentId"),
                    "human_origin":record.get("human_origin"),
                    "call_id":payload.get("call_id").or_else(||record.get("tool_use_id")),
                    "timestamp_ms":ts_ms,"lineage":lineage,
                    "usage_evidence":if request.agent=="pi" {record.get("message").and_then(|m|m.get("usage"))} else if payload.get("type").and_then(Value::as_str)==Some("token_count") {payload.get("info")} else {record.get("message").and_then(|m|m.get("usage"))}}));
            }
            offset = end;
        }
    }
    let path = if request.source_path.is_empty() {
        "session.jsonl"
    } else {
        &request.source_path
    };
    let pi_content = if request.agent == "pi" {
        pi_adapter(&values)?
    } else {
        String::new()
    };
    let parser_content = if request.agent == "pi" {
        &pi_content
    } else if is_document {
        content
    } else {
        &valid_source
    };
    let parser_agent = if request.agent == "pi" {
        "claude"
    } else {
        &request.agent
    };
    let mut session = agent_session::parse_session_content(
        parser_agent,
        Path::new(path),
        UNIX_EPOCH,
        parser_content,
    )
    .ok_or("source did not yield an agent session")?;
    if request.agent == "pi" {
        session.agent_type = "pi".into();
    }
    let mut operations = Vec::new();
    let mut by_timestamp: HashMap<i64, Option<usize>> = HashMap::new();
    let mut by_call: HashMap<&str, Option<usize>> = HashMap::new();
    for (index, record) in records.iter().enumerate() {
        if let Some(timestamp) = record["timestamp_ms"].as_i64() {
            by_timestamp
                .entry(timestamp)
                .and_modify(|entry| *entry = None)
                .or_insert(Some(index));
        }
        if let Some(call) = record["call_id"].as_str() {
            by_call
                .entry(call)
                .and_modify(|entry| *entry = None)
                .or_insert(Some(index));
        }
    }
    let location = |timestamp: Option<i64>, call_id: Option<&str>| -> Value {
        let matched = call_id
            .and_then(|id| by_call.get(id).copied().flatten())
            .or_else(|| timestamp.and_then(|ts| by_timestamp.get(&ts).copied().flatten()));
        if let Some(index) = matched {
            json!({"source_line":records[index]["source_line"],"byte_start":records[index]["byte_start"],
            "byte_end":records[index]["byte_end"],"source_event_id":records[index]["event_id"]})
        } else {
            json!({"source_line":null,"byte_start":null,"byte_end":null,"source_event_id":null})
        }
    };
    for prompt in &session.events.prompts {
        operations.push(json!({"id":digest(format!("{}:prompt:{}:{}",request.source_id,prompt.index,prompt.text_hash).as_bytes()),
            "kind":"prompt","timestamp_ms":prompt.ts_ms,"title":prompt.preview,"text":prompt.text,
            "prompt_index":prompt.index,"metrics":{},"location":location(prompt.ts_ms,None)}));
    }
    for response in &session.events.llm_responses {
        operations.push(json!({"id":digest(format!("{}:llm:{}:{}:{}",request.source_id,response.prompt_index,response.source_id,response.text_hash).as_bytes()),
            "kind":"llm","timestamp_ms":response.ts_ms,"title":response.preview,"text":response.text,
            "prompt_index":response.prompt_index,"source_native_id":response.source_id,"model":response.model,
            "metrics":{},"upstream_token_fields":{"input":response.input_tokens,"output":response.output_tokens,"cache":response.cache_tokens,"total":response.total_tokens},
            "location":location(response.ts_ms,None)}));
    }
    for (index, tool) in session.events.tools.iter().enumerate() {
        operations.push(json!({"id":digest(format!("{}:tool:{}:{}",request.source_id,index,tool.call_id.as_deref().unwrap_or("")).as_bytes()),
            "kind":"tool","timestamp_ms":tool.ts_ms,"title":tool.tool_name,"text":tool.command,
            "prompt_index":tool.prompt_index,"call_id":tool.call_id,"category":tool.category,"status":tool.status,
            "metrics":{},"location":location(tool.ts_ms,tool.call_id.as_deref())}));
    }
    operations.sort_by_key(|value| value["timestamp_ms"].as_i64().unwrap_or(i64::MAX));
    let mut warnings = vec![
        "upstream IR usage zero does not establish source availability; billing must inspect source-recorded fields",
        "upstream parser accepts complete snapshots, not independent suffixes",
        "source_records are retained for provenance, fork lineage, exact usage, and content absent from upstream IR",
    ];
    if !quarantined.is_empty() {
        warnings.push(
            "coverage gap: malformed records quarantined; raw bytes retained in source archive",
        );
    }
    Ok(
        json!({"schema":SCHEMA,"worker_version":env!("CARGO_PKG_VERSION"),"parser":{"name":"agent-session","version":"0.5.17"},
        "source_id":request.source_id,"source_sha256":digest(content.as_bytes()),
        "complete_bytes":complete_bytes,"pending_bytes":source.len()-complete_bytes,
        "metadata":source_metadata(&values),
        "coverage":{"status":if quarantined.is_empty() {"complete"} else {"partial"},
            "complete_records":records.len()+quarantined.len(),"valid_records":records.len(),
            "quarantined_records":quarantined.len(),"complete_bytes":complete_bytes,
            "pending_bytes":source.len()-complete_bytes},
        "quarantined_records":quarantined,
        "session":session,"source_records":records,"operations":operations,
        "measurement_policy":"source_recorded_only",
        "warnings":warnings}),
    )
}

/// Pi's native tree remains in source_records. The compatibility view is ephemeral:
/// agent-session owns the common IR and source positions always refer to original bytes.
fn pi_adapter(records: &[Value]) -> Result<String, String> {
    let header = records
        .iter()
        .find(|r| r["type"] == "session")
        .ok_or("Pi source has no session header")?;
    let session_id = header["id"].as_str().ok_or("Pi session has no id")?;
    let mut output = String::new();
    for record in records {
        if record["type"] != "message" {
            continue;
        }
        let message = &record["message"];
        let role = message["role"].as_str().unwrap_or("");
        if !["user", "assistant", "toolResult"].contains(&role) {
            continue;
        }
        let mut blocks = Vec::new();
        if let Some(text) = message["content"].as_str() {
            blocks.push(json!({"type":"text","text":text}));
        }
        if let Some(parts) = message["content"].as_array() {
            for part in parts {
                match part["type"].as_str().unwrap_or("") {
                    "text" => blocks.push(part.clone()),
                    "toolCall" => blocks.push(json!({"type":"tool_use","id":part["id"],
                        "name":part["name"],"input":part["arguments"]})),
                    _ => (),
                }
            }
        }
        let mapped_role = if role == "assistant" {
            "assistant"
        } else {
            "user"
        };
        if role == "toolResult" {
            blocks = vec![
                json!({"type":"tool_result","tool_use_id":message["toolCallId"],
                "content":blocks,"is_error":message["isError"]}),
            ];
        }
        let mut mapped = json!({"type":mapped_role,"sessionId":session_id,"uuid":record["id"],
            "parentUuid":record["parentId"],"timestamp":record["timestamp"],"cwd":header["cwd"],
            "message":{"id":record["id"],"role":mapped_role,"model":message["model"],"content":blocks}});
        if let Some(usage) = message.get("usage") {
            let mut target = serde_json::Map::new();
            for (native, unified) in [
                ("input", "input_tokens"),
                ("output", "output_tokens"),
                ("cacheRead", "cache_read_input_tokens"),
                ("cacheWrite", "cache_creation_input_tokens"),
            ] {
                if let Some(value) = usage.get(native) {
                    target.insert(unified.into(), value.clone());
                }
            }
            mapped["message"]["usage"] = Value::Object(target);
        }
        output.push_str(&serde_json::to_string(&mapped).map_err(|_| "cannot adapt Pi record")?);
        output.push('\n');
    }
    Ok(output)
}

fn source_metadata(records: &[Value]) -> Value {
    let mut metadata = json!({"native_session_id":null,"cwd":null,"started_at":null,
        "last_activity_at":null,"parent_session_id":null,"first_user_message":null,"abstract":null});
    let mut first_ts: Option<(i64, String)> = None;
    let mut last_ts: Option<(i64, String)> = None;
    for record in records {
        let payload = record.get("payload").unwrap_or(record);
        let kind = record["type"].as_str().unwrap_or("");
        if ["session_meta", "session"].contains(&kind) {
            for (target, keys) in [
                ("native_session_id", vec!["id"]),
                ("cwd", vec!["cwd"]),
                (
                    "parent_session_id",
                    vec!["forked_from_id", "parent_thread_id", "parent_session_id"],
                ),
            ] {
                if let Some(value) = keys
                    .iter()
                    .find_map(|key| payload.get(*key))
                    .filter(|v| !v.is_null())
                {
                    metadata[target] = value.clone();
                }
            }
        }
        for key in ["cwd", "sessionId"] {
            let target = if key == "cwd" {
                "cwd"
            } else {
                "native_session_id"
            };
            if metadata[target].is_null() && record.get(key).is_some() {
                metadata[target] = record[key].clone();
            }
        }
        if metadata["abstract"].is_null() {
            if let Some(value) = record
                .get("abstract")
                .or_else(|| payload.get("abstract"))
                .filter(|v| v.is_string())
            {
                metadata["abstract"] = value.clone();
            }
        }
        if let Some(ts) = record
            .get("timestamp")
            .or_else(|| payload.get("timestamp"))
            .and_then(Value::as_str)
            .and_then(|s| {
                chrono::DateTime::parse_from_rfc3339(s)
                    .ok()
                    .map(|d| (d.timestamp_millis(), s.to_string()))
            })
        {
            if first_ts.as_ref().is_none_or(|first| ts.0 < first.0) {
                first_ts = Some(ts.clone());
            }
            if last_ts.as_ref().is_none_or(|last| ts.0 > last.0) {
                last_ts = Some(ts);
            }
        }
        let message = record.get("message").unwrap_or(payload);
        if metadata["first_user_message"].is_null() && message["role"] == "user" {
            let text = if let Some(text) = message["content"].as_str() {
                text.to_owned()
            } else {
                message["content"]
                    .as_array()
                    .map(|parts| {
                        parts
                            .iter()
                            .filter(|p| p["type"] == "text" || p["type"] == "input_text")
                            .filter_map(|p| p["text"].as_str())
                            .collect::<Vec<_>>()
                            .join("\n")
                    })
                    .unwrap_or_default()
            };
            if !text.is_empty() {
                metadata["first_user_message"] = json!(text);
            }
        }
    }
    metadata["started_at"] = first_ts.map(|(_, s)| json!(s)).unwrap_or(Value::Null);
    metadata["last_activity_at"] = last_ts.map(|(_, s)| json!(s)).unwrap_or(Value::Null);
    metadata
}

fn main() -> io::Result<()> {
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let line = line?;
        let value: Result<Value, _> = serde_json::from_str(&line);
        let id = value
            .as_ref()
            .ok()
            .and_then(|v| v.get("id"))
            .cloned()
            .unwrap_or(Value::Null);
        let result = value
            .map_err(|_| "invalid request JSON".to_string())
            .and_then(|value| {
                serde_json::from_value::<Request>(value)
                    .map_err(|_| "invalid request schema".into())
            })
            .and_then(|request| parse(&request));
        let response = match result {
            Ok(data) => json!({"id":id,"ok":true,"result":data}),
            Err(error) => json!({"id":id,"ok":false,"error":error}),
        };
        serde_json::to_writer(&mut stdout, &response)?;
        stdout.write_all(b"\n")?;
        stdout.flush()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(content: &str) -> Request {
        Request {
            _id: json!(1),
            op: "parse".into(),
            source_id: "machine/session".into(),
            agent: "codex".into(),
            content: content.into(),
            source_path: "rollout.jsonl".into(),
            input_file: None,
        }
    }

    const SOURCE: &str = concat!(
        "{\"type\":\"session_meta\",\"payload\":{\"id\":\"test-session\",\"cwd\":\"/project\",\"forked_from_id\":\"parent\"}}\n",
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"task_started\",\"started_at\":1792368000}}\n",
        "{\"timestamp\":\"2026-10-19T00:00:01Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"修复认证\"}]}}\n",
        "{\"timestamp\":\"2026-10-19T00:00:02Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":{\"input_tokens\":20,\"cached_input_tokens\":5,\"output_tokens\":3,\"total_tokens\":23},\"last_token_usage\":{\"input_tokens\":20,\"cached_input_tokens\":5,\"output_tokens\":3,\"total_tokens\":23}}}}\n"
    );

    #[test]
    fn calls_upstream_and_preserves_source_lineage_and_bytes() {
        let output = parse(&request(SOURCE)).unwrap();
        assert_eq!(output["session"]["session_id"], "test-session");
        assert_eq!(
            output["session"]["events"]["prompts"][0]["text"],
            "修复认证"
        );
        assert_eq!(
            output["source_records"][0]["lineage"]["forked_from_id"],
            "parent"
        );
        assert_eq!(output["source_records"][3]["byte_end"], SOURCE.len());
        // Codex records cached input inside input_tokens; upstream subtracts it.
        assert_eq!(output["session"]["usage"]["input_tokens"], 15);
        assert_eq!(output["session"]["usage"]["cache_read_tokens"], 5);
        assert_eq!(output["source_sha256"], digest(SOURCE.as_bytes()));
    }

    #[test]
    fn append_and_replay_keep_event_identity_and_hold_partial_records() {
        let original = parse(&request(SOURCE)).unwrap();
        let extended = parse(&request(&format!("{SOURCE}{{\"type\":"))).unwrap();
        assert_eq!(original["source_records"], extended["source_records"]);
        assert_eq!(extended["complete_bytes"], SOURCE.len());
        assert!(extended["pending_bytes"].as_u64().unwrap() > 0);
    }

    #[test]
    fn malformed_complete_line_is_quarantined_with_original_offsets() {
        let bad = "broken\n";
        let last = SOURCE.lines().nth(2).unwrap();
        let content = format!("{SOURCE}{bad}{last}\n");
        let result = parse(&request(&content)).unwrap();
        assert_eq!(result["coverage"]["status"], "partial");
        assert_eq!(result["coverage"]["quarantined_records"], 1);
        assert_eq!(result["quarantined_records"][0]["byte_start"], SOURCE.len());
        assert_eq!(
            result["source_records"][4]["byte_start"],
            SOURCE.len() + bad.len()
        );
        assert_eq!(result["source_records"][4]["source_line"], 6);
        assert_eq!(result["source_sha256"], digest(content.as_bytes()));
    }

    #[test]
    fn file_partial_utf8_is_pending_until_record_append_completes() {
        let path =
            std::env::temp_dir().join(format!("trajectory-worker-utf8-{}", std::process::id()));
        let mut file_request = request("");
        file_request.input_file = Some(path.to_string_lossy().into_owned());
        let prefix = format!(
            "{SOURCE}{{\"type\":\"response_item\",\"payload\":{{\"type\":\"message\",\"role\":\"user\",\"content\":[{{\"type\":\"input_text\",\"text\":\""
        );
        let mut bytes = prefix.as_bytes().to_vec();
        bytes.extend_from_slice(&"继续".as_bytes()[..1]);
        std::fs::write(&path, &bytes).unwrap();
        let partial = parse(&file_request).unwrap();
        assert_eq!(partial["complete_bytes"], SOURCE.len());
        assert_eq!(partial["pending_bytes"], bytes.len() - SOURCE.len());
        assert_eq!(partial["source_sha256"], digest(SOURCE.as_bytes()));
        bytes.extend_from_slice(&"继续".as_bytes()[1..]);
        bytes.extend_from_slice(b"\"}]}}\n");
        std::fs::write(&path, &bytes).unwrap();
        let completed = parse(&file_request).unwrap();
        assert_eq!(completed["complete_bytes"], bytes.len());
        assert_eq!(completed["pending_bytes"], 0);
        assert_eq!(completed["source_records"].as_array().unwrap().len(), 5);
        assert_eq!(completed["session"]["events"]["prompts"][1]["text"], "继续");
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn invalid_utf8_in_complete_record_or_document_fails() {
        let path = std::env::temp_dir().join(format!(
            "trajectory-worker-invalid-utf8-{}",
            std::process::id()
        ));
        std::fs::write(&path, b"{\"text\":\"\xe7\"}\n").unwrap();
        let mut file_request = request("");
        file_request.input_file = Some(path.to_string_lossy().into_owned());
        assert!(parse(&file_request).unwrap_err().contains("UTF-8"));
        file_request.agent = "gemini".into();
        std::fs::write(&path, b"{\"text\":\"\xe7").unwrap();
        assert!(parse(&file_request).unwrap_err().contains("UTF-8"));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn repeated_cumulative_usage_does_not_double_count() {
        let usage = SOURCE.lines().last().unwrap();
        let output = parse(&request(&format!("{SOURCE}{usage}\n"))).unwrap();
        assert_eq!(output["session"]["usage"]["input_tokens"], 15);
        assert_eq!(output["session"]["usage"]["output_tokens"], 3);
    }

    #[test]
    fn inherited_fork_context_is_not_a_new_human_prompt() {
        let inherited = "{\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"inherited\"}]}}\n";
        let boundary = SOURCE.find('\n').unwrap() + 1;
        let fork = format!(
            "{}{}{}",
            &SOURCE[..boundary],
            inherited,
            &SOURCE[boundary..]
        );
        let output = parse(&request(&fork)).unwrap();
        assert_eq!(
            output["session"]["events"]["prompts"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(output["source_records"].as_array().unwrap().len(), 5);
    }

    #[test]
    fn claude_usage_retains_cache_write_and_read_categories() {
        let content = concat!(
            "{\"type\":\"user\",\"sessionId\":\"claude-session\",\"message\":{\"role\":\"user\",\"content\":\"fix auth\"}}\n",
            "{\"type\":\"assistant\",\"sessionId\":\"claude-session\",\"message\":{\"id\":\"msg-1\",\"model\":\"claude-sonnet-4-5\",\"content\":[{\"type\":\"text\",\"text\":\"done\"}],\"usage\":{\"input_tokens\":10,\"output_tokens\":2,\"cache_creation_input_tokens\":7,\"cache_read_input_tokens\":4}}}\n"
        );
        let mut source = request(content);
        source.agent = "claude".into();
        let output = parse(&source).unwrap();
        assert_eq!(output["session"]["usage"]["cache_creation_tokens"], 7);
        assert_eq!(output["session"]["usage"]["cache_read_tokens"], 4);
        assert!(
            output["operations"]
                .as_array()
                .unwrap()
                .iter()
                .all(|operation| operation["metrics"] == json!({}))
        );
    }
    const PI_SOURCE: &str = concat!(
        r#"{"type":"session","version":3,"id":"pi-session","timestamp":"2026-10-01T10:00:00Z","cwd":"/home/sdu/embodied","parent_session_id":"pi-parent"}"#,
        "\n",
        r#"{"type":"message","id":"u1","parentId":null,"timestamp":"2026-10-01T10:00:01Z","message":{"role":"user","content":[{"type":"text","text":"Compare AI and CPM"}]}}"#,
        "\n",
        r#"{"type":"message","id":"a1","parentId":"u1","timestamp":"2026-10-01T10:00:02Z","message":{"role":"assistant","model":"test-model","content":[{"type":"thinking","thinking":"private"},{"type":"toolCall","id":"call-1","name":"bash","arguments":{"command":"pwd"}}],"usage":{"input":20,"output":4,"cacheRead":8,"cacheWrite":2,"reasoning":3,"cost":{"total":0.001}}}}"#,
        "\n",
        r#"{"type":"message","id":"t1","parentId":"a1","timestamp":"2026-10-01T10:00:03Z","message":{"role":"toolResult","toolCallId":"call-1","toolName":"bash","content":[{"type":"text","text":"/home/sdu/embodied"}],"isError":false}}"#,
        "\n",
        r#"{"type":"message","id":"u2","parentId":"u1","timestamp":"2026-10-01T10:00:04Z","message":{"role":"user","content":[{"type":"text","text":"Alternative branch"}]}}"#,
        "\n",
        r#"{"type":"message","id":"a2","parentId":"u2","timestamp":"2026-10-01T10:00:05Z","message":{"role":"assistant","model":"test-model","content":[{"type":"text","text":"Compared"}]}}"#,
        "\n"
    );

    #[test]
    fn pi_native_adapter_preserves_branch_usage_unknowns_and_locations() {
        let mut req = request(PI_SOURCE);
        req.agent = "pi".into();
        let result = parse(&req).unwrap();
        assert_eq!(result["session"]["session_id"], "pi-session");
        assert_eq!(result["session"]["agent_type"], "pi");
        assert_eq!(result["metadata"]["cwd"], "/home/sdu/embodied");
        assert_eq!(result["metadata"]["parent_session_id"], "pi-parent");
        assert_eq!(
            result["metadata"]["first_user_message"],
            "Compare AI and CPM"
        );
        assert_eq!(
            result["metadata"]["last_activity_at"],
            "2026-10-01T10:00:05Z"
        );
        assert_eq!(result["source_records"][4]["parent_native_id"], "u1");
        assert_eq!(
            result["source_records"][2]["usage_evidence"]["cacheWrite"],
            2
        );
        assert!(result["source_records"][5]["usage_evidence"].is_null());
        assert!(result["source_records"][1]["human_origin"].is_null());
        assert!(result["metadata"]["abstract"].is_null());
        assert_eq!(result["session"]["usage"]["cache_creation_tokens"], 2);
        assert_eq!(result["session"]["usage"]["cache_read_tokens"], 8);
        let ops = result["operations"].as_array().unwrap();
        assert!(
            ops.iter()
                .any(|o| o["kind"] == "tool" && o["location"]["source_line"] == 3)
        );
        assert!(ops.iter().all(|o| o["metrics"] == json!({})));
        assert_eq!(result["source_sha256"], digest(PI_SOURCE.as_bytes()));
        let replay = parse(&req).unwrap();
        assert_eq!(result["operations"], replay["operations"]);
    }
}
