import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from reportlab.pdfgen import canvas
from sqlalchemy import select
from app.core import ROOT,Session,seed_users,User,uid,settings
from app.models import Vendor,Performance,RFQ,Item,Submission
from app.schemas import DEFAULT_WEIGHTS
from app.documents import upload,process

def pdf(path,title,lines):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return
    c=canvas.Canvas(str(path),invariant=1);c.setTitle(title);c.setFont('Helvetica-Bold',18);c.drawString(45,795,title)
    y=755;c.setFont('Helvetica',11)
    for line in lines:
        if y<70:c.showPage();y=780;c.setFont('Helvetica',11)
        c.drawString(45,y,line);y-=24
    c.save()

def seed():
    with Session() as db:
        seed_users(db,['analyst','manager']);owner=db.scalar(select(User).where(User.role=='analyst'))
        specs=[('Alpha',58000,20,95,'compliant',30),('Beta',52000,12,80,'compliant',12),('Gamma',55000,16,87,'conditional',24)]
        rfq=db.scalar(select(RFQ).where(RFQ.number=='RFQ-DEMO-100'))
        if not rfq:
            rfq=RFQ(id=uid(),owner_id=owner.id,number='RFQ-DEMO-100',title='100 office laptops',budget=7000000,currency='INR',due_date='2026-12-01',status='OPEN',weights_json=DEFAULT_WEIGHTS)
            db.add(rfq);db.flush();db.add(Item(rfq_id=rfq.id,description='Business laptop: 16GB RAM, 512GB SSD',quantity=100,unit='piece',target_price=58000));db.commit()
        labels=[]
        for name,price,days,quality,compliance,warranty in specs:
            vendor=db.scalar(select(Vendor).where(Vendor.name==name))
            if not vendor:
                vendor=Vendor(id=uid(),name=name,compliance_status=compliance);db.add(vendor);db.flush();db.add(Performance(vendor_id=vendor.id,value=quality,period='2026-Q3',source='Synthetic labelled demo supplier review'));db.commit()
            sub=db.scalar(select(Submission).where(Submission.rfq_id==rfq.id,Submission.vendor_id==vendor.id))
            if not sub:sub=Submission(id=uid(),rfq_id=rfq.id,vendor_id=vendor.id);db.add(sub);db.commit()
            quote=ROOT/'sample-data'/'quotations'/(name.lower()+'.pdf')
            total=price*100*1.18
            lines=[f'Vendor: {name}','Item: Business laptop 16GB RAM / 512GB SSD','Currency: INR','Quantity: 100',f'Unit price: {price}','Tax: 18',f'Total: {total:.2f}',f'Delivery days: {days}','Payment: Net 30 days',f'Warranty months: {warranty}','Document purpose: synthetic public portfolio demonstration.']
            pdf(quote,name+' Quotation',lines)
            clauses=['1. Scope: Supply 100 business laptops matching RFQ specifications.',
                     '2. Termination: Buyer and supplier may terminate with 30 days notice.',
                     '3. Liability: Liability is capped at the contract value.',
                     '4. Payment: Net 30 days after accepted delivery.',
                     '5. Data protection: Supplier shall protect all buyer data.',
                     '6. Warranty: Manufacturer warranty applies for the agreed term.']
            if name=='Beta':
                clauses[1]='2. Termination: Supplier may terminate with 7 days notice.'
                clauses[3]='4. Payment: 100% advance payment required before shipment.'
            contract=ROOT/'sample-data'/'contracts'/(name.lower()+'.pdf');pdf(contract,name+' Commercial Terms',clauses)
            for kind,path in [('quotation',quote),('contract',contract)]:
                d=upload(db,sub,kind,path.name,path.read_bytes());db.commit();process(db,d)
            labels.append({'vendor':name,'currency':'INR','quantity':100,'unit_price':price,'tax':18,'total':total,'delivery_days':days,'payment':'Net 30 days','warranty_months':warranty})
        (ROOT/'sample-data'/'expected-extractions.json').write_text(json.dumps(labels,indent=2))
        (ROOT/'sample-data'/'vendors.json').write_text(json.dumps([{'name':n,'quality':q,'compliance':c} for n,p,d,q,c,w in specs],indent=2))
        print('Seeded three vendors, labelled PDF quotations, contracts and RFQ '+rfq.number)
if __name__=='__main__':seed()
