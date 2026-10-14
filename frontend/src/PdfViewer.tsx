import {useEffect,useState} from 'react';
export default function PdfViewer({id,page=1}:{id:string,page?:number}){
 const [url,setUrl]=useState('');const [error,setError]=useState('');
 useEffect(()=>{let objectURL='';let active=true;fetch('/api/documents/'+id+'/file',{headers:{Authorization:'Bearer '+sessionStorage.getItem('token')}}).then(async r=>{if(!r.ok)throw Error('PDF could not be opened');objectURL=URL.createObjectURL(await r.blob());if(active)setUrl(objectURL)}).catch(e=>setError(e.message));return()=>{active=false;if(objectURL)URL.revokeObjectURL(objectURL)}},[id]);
 return error?<p className="error">{error}</p>:url?<iframe title={'Source PDF page '+page} src={url+'#page='+page} style={{width:'100%',height:600,border:'1px solid #30475c',borderRadius:8}}/>:<p>Loading source PDF…</p>
}
