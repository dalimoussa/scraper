import json

from bet365 import Bet365AndroidSession

with open("config.json", encoding="utf8") as fp:
    config = json.load(fp)

print("Fetching soccer page using android api")

session = Bet365AndroidSession(
    config["api_url"],
    config["api_key"],
    proxy=config["proxy"] or None,
    verify=False,
    host=config["host"]
)

session.go_homepage()

sports = session.extract_available_sports()
print("sports")
for sport in sports:
    print(f"{sport.name} -> {sport.PD}")

session.get_sport_homepage(next(filter(lambda m: m.name == "Soccer", sports)))
