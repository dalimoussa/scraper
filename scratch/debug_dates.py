from bet365_internal import is_upcoming_pre_match, _init_sports_ref_store, _SPORTS_REF_STORE
from datetime import datetime

_init_sports_ref_store()
now = datetime.now()

for sp in ["Cycling", "F1"]:
    ref = _SPORTS_REF_STORE.get(sp, [])
    print(f"{sp}: {len(ref)} matches in ref store")
    for m in ref[:3]:
        valid = is_upcoming_pre_match(m.get("date"), m.get("kickoff"), sp)
        comp = m.get("competition")
        date = m.get("date")
        kickoff = m.get("kickoff")
        print(f"  {comp} | date={date} | kickoff={kickoff} | valid={valid}")
