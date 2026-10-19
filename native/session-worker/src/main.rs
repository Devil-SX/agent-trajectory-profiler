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
            json!({"schema": SCHEMA, "parser": {"name":"agent-session", "version":"0.5.17"}}),
        );
    }
    if request.op != "parse" {
        return Err("unsupported operation".into());
    }
    if request.source_id.is_empty() {
        return Err("source_id is required".into());
    }
    if !["codex", "claude", "gemini", "cursor", "codebuddy"].contains(&request.agent.as_str()) {
        return Err("unsupported agent".into());
    }
    // JSONL appends can stop in the middle of an encoded Unicode character or
    // JSON record. The transport owns UTF-8 decoding; we consume complete lines.
    let file_content = request
        .input_file
        .as_ref()
        .map(std::fs::read_to_string)
        .transpose()
        .map_err(|_| "cannot read internal input_file")?;
    if file_content.is_some() && !request.content.is_empty() {
        return Err("content and input_file are mutually exclusive".into());
    }
    let source = file_content.as_deref().unwrap_or(&request.content);
    let is_document = request.agent == "gemini";
    let complete_bytes = if is_document || source.ends_with('\n') {
        source.len()
    } else {
        source.rfind('\n').map_or(0, |i| i + 1)
    };
    let content = &source[..complete_bytes];
    let mut records = Vec::new();
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
                let record: Value = serde_json::from_str(line)
                    .map_err(|_| format!("invalid source JSON at line {}", ordinal + 1))?;
                let payload = record.get("payload").unwrap_or(&record);
                let ts_ms = record
                    .get("timestamp")
                    .and_then(Value::as_str)
                    .and_then(|ts| chrono::DateTime::parse_from_rfc3339(ts).ok())
                    .map(|ts| ts.timestamp_millis());
                let lineage = if record.get("type").and_then(Value::as_str) == Some("session_meta")
                {
                    json!({"id":payload.get("id"),"forked_from_id":payload.get("forked_from_id"),"parent_thread_id":payload.get("parent_thread_id"),"source":payload.get("source")})
                } else {
                    Value::Null
                };
                records.push(json!({"ordinal":ordinal,"source_line":ordinal+1,"byte_start":offset,"byte_end":end,
                    "event_id":digest(format!("{}:{}:{}",request.source_id,ordinal,line).as_bytes()),
                    "record_sha256":digest(line.trim_end_matches(['\r','\n']).as_bytes()),
                    "record_type":record.get("type"),"payload_type":payload.get("type"),
                    "native_id":payload.get("id").or_else(||record.get("uuid")),
                    "call_id":payload.get("call_id").or_else(||record.get("tool_use_id")),
                    "timestamp_ms":ts_ms,"lineage":lineage,
                    "usage_evidence":if payload.get("type").and_then(Value::as_str)==Some("token_count") {payload.get("info")} else {None}}));
            }
            offset = end;
        }
    }
    let path = if request.source_path.is_empty() {
        "session.jsonl"
    } else {
        &request.source_path
    };
    let session =
        agent_session::parse_session_content(&request.agent, Path::new(path), UNIX_EPOCH, content)
            .ok_or("source did not yield an agent session")?;
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
    Ok(
        json!({"schema":SCHEMA,"parser":{"name":"agent-session","version":"0.5.17"},
        "source_id":request.source_id,"source_sha256":digest(content.as_bytes()),
        "complete_bytes":complete_bytes,"pending_bytes":source.len()-complete_bytes,
        "session":session,"source_records":records,"operations":operations,
        "measurement_policy":"source_recorded_only",
        "warnings":["upstream IR usage zero does not establish source availability; billing must inspect source-recorded fields",
                    "upstream parser accepts complete snapshots, not independent suffixes",
                    "source_records are retained for provenance, fork lineage, exact usage, and content absent from upstream IR"]}),
    )
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
    fn malformed_complete_line_is_not_silently_dropped() {
        assert!(parse(&request(&format!("{SOURCE}broken\n"))).is_err());
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
        let fork = format!("{}{}{}", &SOURCE[..boundary], inherited, &SOURCE[boundary..]);
        let output = parse(&request(&fork)).unwrap();
        assert_eq!(output["session"]["events"]["prompts"].as_array().unwrap().len(), 1);
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
        assert!(output["operations"].as_array().unwrap().iter().all(|operation| operation["metrics"] == json!({})));
    }
}
