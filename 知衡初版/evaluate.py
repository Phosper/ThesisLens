"""Fixed 20-case retrieval evaluation, with optional paid model calls and resumable logs."""
import argparse
import hashlib
import json
import core
import retrieval
from check_stage3_live import measure

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    raw=(core.APP/'evaluation_cases.json').read_text('utf-8');corpus=json.loads(raw);digest=hashlib.sha256(raw.encode()).hexdigest()
    output=core.DATA/'stage4_evaluation.json';result={'created_at':core.now(),'corpus_sha256':digest,'annotation_note':corpus['annotation_note'],'live':args.live,'cases':[]}
    if args.resume and output.exists():
        previous=json.loads(output.read_text('utf-8'))
        if previous['corpus_sha256']==digest and previous['live']==args.live:result=previous
    completed={x['id'] for x in result['cases']}
    core.ensure_index()
    for case in corpus['cases']:
        if case['id'] in completed:continue
        rows=core.search(case['question'],case['code'],case['cutoff'],5,period=case['period'],include_industry=False)
        item={'id':case['id'],'keyword':measure(rows,case),'gold':{'source_id':case['source_id'],'pages':case['pages']}}
        if args.live:
            pack=retrieval.search(case['question'],case['code'],case['cutoff'],5,period=case['period'],include_industry=False)
            assert all(r['publication_date']<=case['cutoff'] and r['stock_code']==case['code'] and r['report_period']==case['period'] for r in pack['data'])
            item.update(enhanced=measure(pack['data'],case),mode=pack['mode'],warnings=pack['warnings'],search_id=pack['id'],model_calls=len(pack['model_calls']),
                        top_pages=[{'source_id':r['source_id'],'page':r.get('pdf_page')} for r in pack['data'][:5]])
        result['cases'].append(item);output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps({'case':item['id'],'keyword':item['keyword']['hit_at_5'],'enhanced':item.get('enhanced',{}).get('hit_at_5'),'mode':item.get('mode')},ensure_ascii=False),flush=True)
    result['summary']={k:{'hit_count':sum(c[k]['hit_at_5'] for c in result['cases']),'sample_count':len(result['cases']),
                          'hit_at_5':sum(c[k]['hit_at_5'] for c in result['cases'])/len(result['cases']),
                          'mrr_at_5':round(sum(c[k]['mrr_at_5'] for c in result['cases'])/len(result['cases']),4)} for k in (['keyword','enhanced'] if args.live else ['keyword'])}
    result['complete']=len(result['cases'])==len(corpus['cases']);result['limitations']='开发者固定题集上的页面命中；不测回答事实正确率、专业投资效果或未知样本泛化。增强含改写、融合与模型重排，不能归因于单一模块。'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8');print(json.dumps(result['summary'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
