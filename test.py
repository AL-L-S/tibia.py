import json
import time

import requests

from tibiapy import Character, Guild

if __name__ == "__main__":
    """
    r = requests.get("https://secure.tibia.com/community/?subtopic=characters&name=General+Jay")
    start = time.perf_counter()
    char = Character._parse(r.text)
    dt = (time.perf_counter() - start) * 1000.0
    with open("output.json", "w") as f:
        f.write(json.dumps(char, indent=4))

    character = Character.from_content(r.text)
    print("Parsed in {0:2f} ms".format(dt))
    """
    r = requests.get("https://secure.tibia.com/community/?subtopic=guilds&page=view&GuildName=Redd+Alliance")
    guild = Guild._parse(r.text)
    print(guild)