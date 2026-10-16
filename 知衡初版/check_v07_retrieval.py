"""Same frozen questions, before/after keyword recall; developer annotation, not blind evaluation."""
import hashlib,json
import core

def main():
    core.ensure_index();file=core.APP/'evaluation_cases_v07.json';digest=hashlib.sha256(file.read_bytes()).hexdigest()
    before=json.loads((core.DATA/'v07_retrieval_before.json').read_text('utf-8'))
    if before['case_sha256']!=digest:raise ValueError('冻结验收题已变化')
    rows=[]
    for c in json.loads(file.read_text('utf-8'))['cases']:
        hits=core.search(c['question'],c['code'],c['cutoff'],5,period=c['period'],include_industry=False)
        rank=next((i for i,r in enumerate(hits,1) if r['source_id']==c['source_id'] and r['pdf_page'] in c['pages']),None)
        rows.append({'id':c['id'],'rank':rank,'top_pages':[r['pdf_page'] for r in hits],
                     'cutoff_valid':all(r['publication_date']<=c['cutoff'] and r['report_period']==c['period'] for r in hits)})
    report={'case_sha256':digest,'checked_at':core.now(),'phase':'after_technical_changes','cases':rows,
            'hit_at_5':sum(r['rank'] is not None for r in rows),'total':len(rows),
            'mrr_at_5':sum(1/r['rank'] if r['rank'] else 0 for r in rows)/len(rows),
            'before_hit_at_5':sum(r['rank'] is not None for r in before['cases']),
            'note':'固定开发验收题，已看过原页定位；不等同独立盲测、金融准确率或投资效果。'}
    (core.DATA/'v07_retrieval_after.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
