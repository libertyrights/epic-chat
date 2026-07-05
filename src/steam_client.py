import aiohttp


class SteamClient:
    def __init__(self, api_key: str, steam_id: str):
        self.api_key = api_key
        self.steam_id = steam_id
        self._game_cache: dict[str, list] = {}

    async def get_owned_games(self, steam_id: str) -> list[dict]:
        if steam_id in self._game_cache:
            return self._game_cache[steam_id]

        url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        params = {
            "key": self.api_key,
            "steamid": steam_id,
            "format": "json",
            "include_appinfo": True,
            "include_played_free_games": True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                games = data.get("response", {}).get("games", [])
                self._game_cache[steam_id] = games
                return games

    async def resolve_vanity(self, vanity: str) -> str | None:
        url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
        params = {"key": self.api_key, "vanityurl": vanity}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("response", {}).get("success") == 1:
                    return data["response"]["steamid"]
        return None

    async def compare_with_friend(self, friend_steam_id: str) -> dict:
        my_games = await self.get_owned_games(self.steam_id)
        friend_games = await self.get_owned_games(friend_steam_id)

        my_set = {g["appid"] for g in my_games}
        friend_set = {g["appid"] for g in friend_games}

        common = my_set & friend_set
        my_unique = my_set - friend_set
        friend_unique = friend_set - my_set

        my_map = {g["appid"]: g["name"] for g in my_games}
        friend_map = {g["appid"]: g["name"] for g in friend_games}

        return {
            "common": sorted(
                ({"appid": a, "name": my_map.get(a, friend_map.get(a, str(a)))}
                 for a in common),
                key=lambda x: x["name"].lower(),
            ),
            "my_uniques": sorted(
                ({"appid": a, "name": my_map.get(a, str(a))} for a in my_unique),
                key=lambda x: x["name"].lower(),
            ),
            "friend_uniques": sorted(
                ({"appid": a, "name": friend_map.get(a, str(a))} for a in friend_unique),
                key=lambda x: x["name"].lower(),
            ),
        }

    async def get_friend_name(self, steam_id: str) -> str | None:
        url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
        params = {"key": self.api_key, "steamids": steam_id}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                players = data.get("response", {}).get("players", [])
                if players:
                    return players[0].get("personaname")
        return None
