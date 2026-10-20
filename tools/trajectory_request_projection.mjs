// Execute the existing Sparkstead projector. This file contains no transcript rules.
import { createHash } from 'node:crypto';
import { openSync, readSync, closeSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
let wire='';
for await (const piece of process.stdin) wire+=piece;
const value=JSON.parse(wire);
try {
  const {projectRecord,PARSER_VERSION}=await import(pathToFileURL(value.projector).href);
  if(PARSER_VERSION!=='sparkstead-trajectory/3')throw new Error('Unsupported projector');
  const state={},records=[],buffer=Buffer.alloc(512*1024),hasher=createHash('sha256');
  const fd=openSync(value.path,'r');let offset=0,line=0,complete=0,carry=Buffer.alloc(0),skipping=false,errors=0;const quarantined=[];
  try {
    while(offset<value.end){
      const read=readSync(fd,buffer,0,Math.min(buffer.length,value.end-offset),offset);
      if(!read)throw new Error('Source truncated');
      offset+=read;
      const block=buffer.subarray(0,read);let start=0;
      for(let i=0;i<read;i++)if(block[i]===10){
        const segment=block.subarray(start,i+1);hasher.update(segment);complete+=segment.length;line++;
        if(!skipping){
          const body=Buffer.concat([carry,segment]);
          if(body.length>buffer.length){errors++;quarantined.push(line);}
          else try {records.push(...projectRecord(JSON.parse(body.toString('utf8')),value.ecosystem,value.source,line,state,value.mapping??{paths:{},names:{}}).filter(record=>record.kind==='request'));}
          catch {errors++;quarantined.push(line);}
        }
        carry=Buffer.alloc(0);skipping=false;start=i+1;
      }
      const rest=block.subarray(start);
      // Hash bytes as soon as read; a trailing incomplete line is rejected below.
      if(rest.length){hasher.update(rest);complete+=rest.length;}
      if(!skipping){carry=Buffer.concat([carry,rest]);if(carry.length>=buffer.length){carry=Buffer.alloc(0);skipping=true;errors++;quarantined.push(line+1);}}
      if(records.length>5000)throw new Error('Too many requests');
    }
  } finally {closeSync(fd);}
  if(carry.length||skipping)throw new Error('Archive prefix ends inside a record');
  process.stdout.write(JSON.stringify({parser_version:PARSER_VERSION,complete_bytes:complete,source_sha256:hasher.digest('hex'),records,parse_errors:errors,quarantined_source_lines:quarantined}));
} catch(error){process.stderr.write(JSON.stringify({error:error?.constructor?.name??'Error'}));process.exitCode=1;}
