import {useState} from 'react';
import {request} from './api';
export default function RFQEditor({detail,onSaved}:{detail:Record<string,any>,onSaved:()=>Promise<void>}){
 const [value,setValue]=useState(JSON.stringify({number:detail.number,title:detail.title,budget:detail.budget,currency:detail.currency,due_date:detail.due_date,weights_json:detail.weights_json,items:detail.items.map((i:Record<string,any>)=>({description:i.description,quantity:i.quantity,unit:i.unit,target_price:i.target_price}))},null,2));
 const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 return <details><summary>Edit RFQ details and evaluation weights</summary><p className="muted">Item changes are permitted before submissions are attached. Analysis and review lock RFQ editing.</p><textarea style={{minHeight:400}} value={value} onChange={e=>setValue(e.target.value)}/>{error&&<p className="error">{error}</p>}<button disabled={busy||!['DRAFT','OPEN'].includes(detail.status)} onClick={async()=>{setBusy(true);setError('');try{await request('/rfqs/'+detail.id,JSON.parse(value),'PATCH');await onSaved()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>Save RFQ</button></details>
}
