"""Additive read-only lab termination contract, not model stop/Task success."""
BASELINE_STATUSES=('STOPPED','REJECTED','STEP_BUDGET_EXHAUSTED')

def valid_turn_status(report):
    if report['status'] in BASELINE_STATUSES:return True
    if report['status']!='RESEARCH_TERMINATED':return False
    c=report.get('control',{})
    return (c.get('schema')=='anima.lab.cognitive_control/0.1' and c.get('profile') in ('r942/0.1','r942/0.2','r943/0.1','r945/0.1')
            and c.get('reason') in ('INFORMATION_SUFFICIENT','SOURCE_UNAVAILABLE','REDUNDANT_OPERATION','NO_SERVICE_READ_VIOLATION'))
