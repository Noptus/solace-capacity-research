/* Local Solace SMF load probe. Requires solclientjs 10.18.3.
 * Session/consumer API usage follows the official Solace Node.js samples.
 * This program measures a test configuration; it does not assert broker peak.
 */
'use strict';
const solace = require('solclientjs');
const {performance} = require('node:perf_hooks');
const readline = require('node:readline');
const cfg = JSON.parse(process.argv[2]);
if (!['publisher','consumer'].includes(cfg.role)) throw Error('invalid role');
if (!(cfg.window >= 1 && cfg.window <= 255)) throw Error('invalid application window');
const sdkWindow=cfg.sdk_window===undefined?255:cfg.sdk_window;
if (!(sdkWindow>=1&&sdkWindow<=255)) throw Error('invalid SDK window');
const factory = new solace.SolclientFactoryProperties();
factory.profile = solace.SolclientFactoryProfiles.version10;
solace.SolclientFactory.init(factory);
let sent=0, acknowledged=0, rejected=0, received=0, pending=0, blocked=0;
let started=false, stopped=false, scheduled=false, start=0, end=0, cpu0, elu0;
let latencySum=0, latencyMax=0, consumer;
let admissionLimit=cfg.initial_credit===undefined?Infinity:cfg.initial_credit;
let lastProgress=0;
let samples=[], lastSample=0, lastAcks=0, lastReceived=0;
const session=solace.SolclientFactory.createSession({
  url:'tcp://127.0.0.1:15555',vpnName:'default',userName:'default',password:'',
  connectRetries:0,reconnectRetries:0,sendBufferMaxSize:8*1024*1024,
  publisherProperties:{windowSize:sdkWindow,
    acknowledgeMode:solace.MessagePublisherAcknowledgeMode.PER_MESSAGE}
});
function emit(value){process.stdout.write(JSON.stringify(value)+'\n');}
function fatal(error){emit({type:'error',error:String(error)});process.exit(1);}
function sample(){
  if(!started)return;
  const now=performance.now();
  samples.push({seconds:(now-start)/1000,interval_seconds:(now-lastSample)/1000,
    ack_delta:acknowledged-lastAcks,received_delta:received-lastReceived,pending});
  lastSample=now;lastAcks=acknowledged;lastReceived=received;
}
function done(){
  if(stopped)return;
  stopped=true;
  sample();
  const cpu=process.cpuUsage(cpu0),elu=performance.eventLoopUtilization(elu0);
  emit({type:'result',role:cfg.role,window:cfg.window,sdk_window:sdkWindow,size:cfg.size,sent,acknowledged,
    rejected,received,pending,blocked,duration_seconds:(performance.now()-start)/1000,
    cpu_user_seconds:cpu.user/1e6,cpu_system_seconds:cpu.system/1e6,
    event_loop_utilization:elu.utilization,
    mean_ack_ms:acknowledged?latencySum/acknowledged:null,max_ack_ms:latencyMax,samples});
  try{if(consumer){consumer.disconnect();consumer.dispose();}session.disconnect();session.dispose();}catch(_){}
  setTimeout(()=>process.exit(0),100);
}
function schedule(){
  if(scheduled||stopped)return;
  scheduled=true;
  setImmediate(()=>{scheduled=false;pump();});
}
const payload='x'.repeat(cfg.size);
function pump(){
  if(!started||stopped)return;
  if(performance.now()>=end){if(pending===0)done();return;}
  let batch=0;
  while(pending<cfg.window && sent<admissionLimit && performance.now()<end && batch<64){
    const message=solace.SolclientFactory.createMessage();
    message.setDestination(solace.SolclientFactory.createTopicDestination('capacity/probe'));
    message.setBinaryAttachment(payload);
    message.setDeliveryMode(solace.MessageDeliveryModeType.PERSISTENT);
    message.setCorrelationKey({sentAt:performance.now()});
    try{session.send(message);sent++;pending++;batch++;}
    catch(error){
      if(error.subcode===solace.ErrorSubcode.INSUFFICIENT_SPACE){blocked++;return;}
      fatal(error);return;
    }
  }
  if(pending<cfg.window&&sent<admissionLimit)schedule();
}
session.on(solace.SessionEventCode.UP_NOTICE,()=>{
  if(cfg.role==='publisher'){emit({type:'ready',role:cfg.role});return;}
  consumer=session.createMessageConsumer({queueDescriptor:{name:cfg.queue,type:solace.QueueType.QUEUE},
    acknowledgeMode:solace.MessageConsumerAcknowledgeMode.CLIENT,createIfMissing:false,windowSize:255});
  consumer.on(solace.MessageConsumerEventName.UP,()=>emit({type:'ready',role:cfg.role}));
  consumer.on(solace.MessageConsumerEventName.CONNECT_FAILED_ERROR,fatal);
  consumer.on(solace.MessageConsumerEventName.DOWN_ERROR,fatal);
  consumer.on(solace.MessageConsumerEventName.MESSAGE,message=>{
    received++;message.acknowledge();
    if(cfg.report_progress && received-lastProgress>=64){
      emit({type:'progress',received});lastProgress=received;
    }
  });
  consumer.connect();
});
session.on(solace.SessionEventCode.CONNECT_FAILED_ERROR,fatal);
session.on(solace.SessionEventCode.DOWN_ERROR,fatal);
session.on(solace.SessionEventCode.CAN_ACCEPT_DATA,schedule);
session.on(solace.SessionEventCode.ACKNOWLEDGED_MESSAGE,event=>{
  pending--;acknowledged++;
  const latency=performance.now()-event.correlationKey.sentAt;
  latencySum+=latency;latencyMax=Math.max(latencyMax,latency);
  schedule();
});
session.on(solace.SessionEventCode.REJECTED_MESSAGE_ERROR,event=>{
  pending--;rejected++;schedule();
});
readline.createInterface({input:process.stdin}).on('line',line=>{
  const command=JSON.parse(line);
  if(command.action==='start' && !started){
    started=true;start=performance.now();lastSample=start;
    end=start+cfg.duration_seconds*1000;cpu0=process.cpuUsage();elu0=performance.eventLoopUtilization();
    setInterval(sample,1000).unref();
    if(cfg.role==='consumer'&&cfg.report_progress){
      setInterval(()=>{if(received!==lastProgress){emit({type:'progress',received});lastProgress=received;}},100).unref();
    }
    if(cfg.role==='publisher'){
      pump();
      setTimeout(()=>{if(pending===0)done();},cfg.duration_seconds*1000+20);
      setTimeout(()=>{if(!stopped)fatal('publisher drain timed out');},cfg.duration_seconds*1000+15000).unref();
    }
  }else if(command.action==='credit'){
    if(!Number.isSafeInteger(command.limit)||command.limit<admissionLimit)fatal('invalid cumulative credit');
    admissionLimit=command.limit;schedule();
  }else if(command.action==='stop'){done();}
});
session.connect();
setTimeout(()=>{if(!started)fatal('start command timed out');},30000).unref();
