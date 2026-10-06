"""Opt-in live public API/model acceptance. Results contain no credentials.

Run with --live. This spends up to two configured model calls per retrieval case.
"""
import argparse
import json
from pathlib import Path

import announcements
import core
import retrieval

def measure(rows,case):
    rank=next((i for i,r in enumerate(rows[:5],1) if r['source_id']==case['source_id'] and r.get('pdf_page') in case['pages']),None)
    return {'hit_at_5':int(rank is not None),'mrr_at_5':round(1/rank,4) if rank else 0,'first_hit':rank}

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--output',default='data/stage3_live.json');args=p.parse_args()
    if not args.live:p.error('Use --live to explicitly permit public requests and configured model calls.')
    corpus=json.loads((core.APP/'retrieval_cases.json').read_text(encoding='utf-8'));result={'created_at':core.now(),'annotation_note':corpus['annotation_note'],'retrieval':[]}
    for case in corpus['cases']:
        baseline=core.search(case['question'],case['code'],case['cutoff'],5,period=case['period'],include_industry=False)
        semantic=retrieval.search(case['question'],case['code'],case['cutoff'],5,period=case['period'],include_industry=False)
        assert all(r['publication_date']<=case['cutoff'] and r['stock_code']==case['code'] and r['report_period']==case['period'] for r in semantic['data'])
        item={'id':case['id'],'question':case['question'],'keyword':measure(baseline,case),'semantic':measure(semantic['data'],case),
              'mode':semantic['mode'],'search_id':semantic['id'],'warnings':semantic['warnings'],'model_calls':len(semantic['model_calls']),
              'top_pages':[{'source_id':r['source_id'],'page':r.get('pdf_page'),'reason':r.get('semantic_reason')} for r in semantic['data']]}
        result['retrieval'].append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
    result['announcements']=announcements.discover({'start':'2026-09-01','end':'2026-10-07','code':''})
    result['announcements'].pop('data',None)
    for c in result['announcements']['companies']:print(json.dumps(c,ensure_ascii=False),flush=True)
    result['summary']={k:{'hit_at_5':sum(r[k]['hit_at_5'] for r in result['retrieval'])/len(corpus['cases']),
                          'mrr_at_5':round(sum(r[k]['mrr_at_5'] for r in result['retrieval'])/len(corpus['cases']),4)} for k in ['keyword','semantic']}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
