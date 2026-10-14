import {beforeEach,describe,it,expect,vi} from 'vitest';
import {request} from './api';
describe('API client boundary',()=>{
 beforeEach(()=>{vi.stubGlobal('sessionStorage',{getItem:()=> 'local-test-token'});vi.stubGlobal('fetch',vi.fn())});
 it('sends authenticated JSON and preserves values',async()=>{vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({id:'record'})} as Response);expect(await request('/rfqs',{budget:100})).toEqual({id:'record'});const [url,options]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('/api/rfqs');expect(options?.headers).toEqual({Authorization:'Bearer local-test-token','Content-Type':'application/json'});expect(options?.body).toBe('{"budget":100}')});
 it('lets the browser set multipart boundaries',async()=>{vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({})} as Response);const form=new FormData();form.set('type','quotation');await request('/documents',form);const options=vi.mocked(fetch).mock.calls[0][1];expect(options?.headers).toEqual({Authorization:'Bearer local-test-token'});expect(options?.body).toBe(form)});
 it('surfaces server validation errors',async()=>{vi.mocked(fetch).mockResolvedValue({ok:false,json:async()=>({detail:'Manager approval required'})} as Response);await expect(request('/reports',{})).rejects.toThrow('Manager approval required')});
 it('uses GET without an artificial request body',async()=>{vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>[]} as Response);await request('/rfqs');expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBe('GET');expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBeUndefined()});
});
