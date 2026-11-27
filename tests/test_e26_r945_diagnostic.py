from copy import deepcopy
import pytest
from labs.virtual_anima_lab.python.lifecycle import e26_r945_diagnostic as d
from labs.virtual_anima_lab.python.lifecycle import e26_reproducibility as f


def fixture(tmp_path):
    request={'model':'frozen','messages':[{'role':'assistant','tool_calls':[{'id':'old','type':'function','function':{'name':'retrieve_memory','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'old','content':'{"strategy":"old","records":[],"returned":0}'}]}
    proposal={'base_request_sha256':d.h._sha(request),'blocks':20,'existing_strategy_levels':['old','new'],
        'order_table':[{'block':i,'cell_order':[0,1,2,3] if i%2==0 else [3,2,1,0]} for i in range(20)]}
    a=tmp_path/'proposal.json';b=tmp_path/'exchange.json';f.write_json(a,proposal);f.write_json(b,{'request':request})
    return d.prepare(a,b,tmp_path/'plan')


def test_four_cells_only_declared_factors(tmp_path):
    plan=fixture(tmp_path);d.validate(plan)
    assert len({c['request_sha256'] for c in plan['cells']})==4
    assert not plan['tool_dispatch'] and plan['planned']==80


def test_undeclared_change_rejected_even_rehashed(tmp_path):
    plan=fixture(tmp_path);p=plan['cells'][1];request=f.read_json(p['request']);request['model']='changed'
    from pathlib import Path
    Path(p['request']).write_text(f.canonical(request))
    p.update(file_sha256=f.file_digest(p['request']),request_sha256=d.h._sha(request))
    with pytest.raises(ValueError,match='undeclared'):d.validate(plan)


def test_order_tamper_rejected(tmp_path):
    plan=fixture(tmp_path);plan['order_table'][0]['cell_order'].reverse()
    with pytest.raises(ValueError,match='order'):d.validate(plan)
