from copy import deepcopy
import json
import pytest
from tests.test_e26_r942_policy import execute
from tests.test_e26_r940_cycle_characterization import memory,crate_event,lookup,OBS
from labs.virtual_anima_lab.python.cognition import control_policy as c
from labs.virtual_anima_lab.python.cognition.coordinator import _rank_memory_matches
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f

def test_r01_casefold_collision():
 from labs.virtual_anima_lab.python.cognition.retrieval_policy import query_key
 assert query_key('ßcrate')!=query_key('sscrate')
 assert query_key(' CRATE ')==query_key('crate')

@pytest.mark.parametrize('mutation',['sufficient','redundant','unavailable','state'])
def test_r02_resealed_control_negatives(tmp_path,monkeypatch,mutation):
 mem=memory(tmp_path,monkeypatch)
 coord,report,records,adapter,wire=execute(tmp_path,mem,[lookup(crate_event(mem),'a')])
 out=tmp_path/'bundle';out.mkdir();raw=f.export_raw(mem,out,7)
 f.export_case(out,7,'C01',report,records,adapter.calls,raw)
 fixture=f.read_json(out/'case-7-C01.json')
 if mutation=='sufficient':
  fixture['turn']['control']['state']['completion']['requirement']['entities']=['lab.item.unseen']
 elif mutation=='redundant':fixture['turn']['control']['reason']='REDUNDANT_OPERATION'
 elif mutation=='unavailable':fixture['turn']['control']['reason']='SOURCE_UNAVAILABLE'
 else:fixture['turn']['control']['state']['gain_key']=[999,999,999]
 # Reseal bytes/checksums, so rejection must be semantic, not hash mismatch.
 (out/'case-7-C01.json').write_text(f.canonical(fixture)+'\n')
 f.seal_bundle(out,{'schema':f.SCHEMA,'git_sha':'a'*40,'world_seeds':[7],'scenarios':[{'id':'C01'}]},complete=True)
 with pytest.raises(ValueError,match='control'):
  f.verify_bundle(out)

def test_new_ranking_exact_and_multi_terms():
 from labs.virtual_anima_lab.python.cognition.retrieval_policy import rank
 rows=[{'entity_ref':'lab.obstacle.aaa'},{'entity_ref':'lab.obstacle.shortcut'}]
 assert rank(rows,'obstacle shortcut')[0]['entity_ref']=='lab.obstacle.shortcut'
 assert rank(rows,'lab.obstacle.shortcut')[0]['entity_ref']=='lab.obstacle.shortcut'
 # Frozen category tie: prefer a whole distinctive terminal token, rather
 # than repeated-letter opaque suffix; lexical fallback remains explicit.
 assert rank(rows,'obstacle')[0]['entity_ref']=='lab.obstacle.shortcut'
 assert _rank_memory_matches(rows,'obstacle')[0]['entity_ref']=='lab.obstacle.aaa'
