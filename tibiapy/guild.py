import datetime
import json
import re
import urllib.parse
from collections import OrderedDict
from typing import List, Optional

import bs4

from tibiapy import abc
from tibiapy.enums import Vocation, try_enum
from tibiapy.errors import InvalidContent
from tibiapy.house import GuildHouse
from tibiapy.utils import parse_tibia_date, parse_tibiadata_date

COLS_INVITED_MEMBER = 2
COLS_GUILD_MEMBER = 6

founded_regex = re.compile(
    r'(?P<desc>.*)The guild was founded on (?P<world>\w+) on (?P<date>[^.]+)\.\nIt is (?P<status>[^.]+).', re.DOTALL)
applications_regex = re.compile(r'Guild is (\w+) for applications\.')
homepage_regex = re.compile(r'The official homepage is at ([\w.]+)\.')
guildhall_regex = re.compile(r'Their home on \w+ is (?P<name>[^.]+). The rent is paid until (?P<date>[^.]+)')
disband_regex = re.compile(r'It will be disbanded on (\w+\s\d+\s\d+)\s([^.]+).')
disband_tibadata_regex = re.compile(r'It will be disbanded, ([^.]+).')
title_regex = re.compile(r'([\w\s]+)\s\(([^)]+)\)')

GUILD_LIST_URL = "https://www.tibia.com/community/?subtopic=guilds&world="
GUILD_LIST_URL_TIBIADATA = "https://api.tibiadata.com/v2/guilds/%s.json"


class Guild(abc.BaseGuild):
    """
    Represents a Tibia guild.

    Attributes
    ------------
    name: :class:`str`
        The name of the guild.
    logo_url: :class:`str`
        The URL to the guild's logo.
    description: :class:`str`, optional
        The description of the guild.
    world: :class:`str`
        The world where this guild is in.
    founded: :class:`datetime.date`
        The day the guild was founded.
    active: :class:`bool`
        Whether the guild is active or still in formation.
    guildhall: :class:`GuildHouse`, optional
        The guild's guildhall if any.
    open_applications: :class:`bool`
        Whether applications are open or not.
    disband_condition: :class:`str`, optional
        The reason why the guild will get disbanded.
    disband_date: :class:`datetime.datetime`, optional
        The date when the guild will be disbanded if the condition hasn't been meet.
    homepage: :class:`str`, optional
        The guild's homepage, if any.
    members: :class:`list` of :class:`GuildMember`
        List of guild members.
    invites: :class:`list` of :class:`GuildInvite`
        List of invited characters.
    """
    __slots__ = ("world", "logo_url", "description", "founded", "active", "guildhall", "open_applications",
                 "disband_condition", "disband_date", "homepage", "members", "invites")

    def __init__(self, name=None, world=None, **kwargs):
        self.name = name
        self.world = world
        self.logo_url = kwargs.get("logo_url")
        self.description = kwargs.get("description")
        _founded = kwargs.get("founded")
        if isinstance(_founded, datetime.datetime):
            self.founded = _founded.date()
        elif isinstance(_founded, datetime.date):
            self.founded = _founded
        elif isinstance(_founded, str):
            self.founded = parse_tibia_date(_founded)
        else:
            self.founded = None
        self.active = kwargs.get("active", False)
        self.guildhall = kwargs.get("guildhall")  # type: Optional[GuildHouse]
        self.open_applications = kwargs.get("open_applications", False)
        self.disband_condition = kwargs.get("disband_condition")
        self.disband_date = kwargs.get("disband_date")
        self.homepage = kwargs.get("homepage")
        self.members = kwargs.get("members", [])  # type: List[GuildMember]
        self.invites = kwargs.get("invites", [])  # type: List[GuildInvite]

    def __repr__(self):
        return "<{0.__class__.__name__} name={0.name!r} world={0.world!r}>".format(self)

    # region Properties
    @property
    def member_count(self):
        """:class:`int`: The number of members in the guild."""
        return len(self.members)

    @property
    def online_members(self) -> List['GuildMember']:
        """:class:`list` of :class:`GuildMember`: List of currently online members."""
        return list(filter(lambda m: m.online, self.members))

    @property
    def ranks(self) -> List[str]:
        """:class:`list` of :class:`str`: Ranks in their hierarchical order."""
        return list(OrderedDict.fromkeys((m.rank for m in self.members)))
    # endregion

    # region Public methods
    @classmethod
    def from_content(cls, content):
        """Creates an instance of the class from the html content of the guild's page.

        Parameters
        -----------
        content: :class:`str`
            The HTML content of the page.

        Returns
        ----------
        :class:`Guild`
            The guild contained in the page or None if it doesn't exist.
        """
        if "An internal error has occurred" in content:
            return None

        parsed_content = cls._beautiful_soup(content)
        try:
            name_header = parsed_content.find('h1')
            guild = Guild(name_header.text.strip())
        except AttributeError:
            raise InvalidContent("content does not belong to a Tibia.com guild page.")

        if not guild._parse_logo(parsed_content):
            raise InvalidContent("content does not belong to a Tibia.com guild page.")

        info_container = parsed_content.find("div", id="GuildInformationContainer")
        guild._parse_guild_info(info_container)
        guild._parse_application_info(info_container)
        guild._parse_guild_homepage(info_container)
        guild._parse_guild_guildhall(info_container)
        guild._parse_guild_disband_info(info_container)
        guild._parse_guild_members(parsed_content)

        if guild.guildhall and guild.members:
            guild.guildhall.owner = guild.members[0].name

        return guild

    @classmethod
    def from_tibiadata(cls, content):
        """Builds a guild object from a TibiaData character response.
        Parameters
        ----------
        content: :class:`str`
            The json string from the TibiaData response.
        Returns
        -------
        :class:`Guild`
            The guild contained in the description or ``None``.
        """
        try:
            json_content = json.loads(content)
        except json.JSONDecodeError:
            return None
        guild_obj = json_content["guild"]
        guild = cls()
        if "error" in guild_obj:
            return None
        guild_data = guild_obj["data"]
        try:
            guild.name = guild_data["name"]
            guild.world = guild_data["world"]
            guild.logo_url = guild_data["guildlogo"]
            guild.description = guild_data["description"]
            guild.founded = parse_tibiadata_date(guild_data["founded"])
            guild.open_applications = guild_data["application"]
        except KeyError:
            return None
        guild.homepage = guild_data.get("homepage")
        guild.active = not guild_data.get("formation", False)
        if isinstance(guild_data["disbanded"], dict):
            guild.disband_date = guild_data["disbanded"]["date"]
            guild.disband_condition = disband_tibadata_regex.search(guild_data["disbanded"]["notification"]).group(1)
        for rank in guild_obj["members"]:
            rank_name = rank["rank_title"]
            for member in rank["characters"]:
                guild.members.append(GuildMember(member["name"], rank_name, member["nick"] or None,
                                                 member["level"], member["vocation"],
                                                 joined=parse_tibiadata_date(member["joined"]),
                                                 online=member["status"] == "online"))
        for invited in guild_obj["invited"]:
            guild.invites.append(GuildInvite(invited["name"], parse_tibiadata_date(invited["invited"])))
        return guild
    # endregion

    # region Private methods
    @classmethod
    def _beautiful_soup(cls, content):
        """
        Parses HTML content into a BeautifulSoup object.

        Parameters
        ----------
        content: :class:`str`
            The HTML content.

        Returns
        -------
        :class:`bs4.BeautifulSoup`
            The parsed content.
        """
        return bs4.BeautifulSoup(content.replace('ISO-8859-1', 'utf-8'), 'lxml',
                                 parse_only=bs4.SoupStrainer("div", class_="BoxContent"))

    def _parse_current_member(self, previous_rank, values):
        """
        Parses the column texts of a member row into a member dictionary.

        Parameters
        ----------
        previous_rank: :class:`dict`[int, str]
            The last rank present in the rows.
        values: tuple[:class:`str`]
            A list of row contents.
        """
        rank, name, vocation, level, joined, status = values
        rank = previous_rank[1] if rank == " " else rank
        title = None
        previous_rank[1] = rank
        m = title_regex.match(name)
        if m:
            name = m.group(1)
            title = m.group(2)
        self.members.append(GuildMember(name, rank, title, int(level), vocation, joined=joined,
                                        online=status == "online"))

    def _parse_application_info(self, info_container):
        """
        Parses the guild's application info.

        Parameters
        ----------
        info_container: :class:`bs4.Tag`
            The parsed content of the information container.
        """
        m = applications_regex.search(info_container.text)
        if m:
            self.open_applications = m.group(1) == "opened"

    def _parse_guild_disband_info(self, info_container):
        """
        Parses the guild's disband info, if available.

        Parameters
        ----------
        info_container: :class:`bs4.Tag`
            The parsed content of the information container.
        """
        m = disband_regex.search(info_container.text)
        if m:
            self.disband_condition = m.group(2)
            self.disband_date = parse_tibia_date(m.group(1).replace("\xa0", " "))

    def _parse_guild_guildhall(self, info_container):
        """
        Parses the guild's guildhall info.

        Parameters
        ----------
        info_container: :class:`bs4.Tag`
            The parsed content of the information container.
        """
        m = guildhall_regex.search(info_container.text)
        if m:
            paid_until = parse_tibia_date(m.group("date").replace("\xa0", " "))
            self.guildhall = GuildHouse(m.group("name"), self.world, paid_until_date=paid_until)

    def _parse_guild_homepage(self, info_container):
        """
        Parses the guild's homepage info.

        Parameters
        ----------
        info_container: :class:`bs4.Tag`
            The parsed content of the information container.
        """
        m = homepage_regex.search(info_container.text)
        if m:
            self.homepage = m.group(1)

    def _parse_guild_info(self, info_container):
        """
        Parses the guild's general information and applies the found values.

        Parameters
        ----------
        info_container: :class:`bs4.Tag`
            The parsed content of the information container.
        """
        m = founded_regex.search(info_container.text)
        if m:
            description = m.group("desc").strip()
            self.description = description if description else None
            self.world = m.group("world")
            self.founded = parse_tibia_date(m.group("date").replace("\xa0", " "))
            self.active = "currently active" in m.group("status")

    def _parse_logo(self, parsed_content):
        """
        Parses the guild logo and saves it to the instance.

        Parameters
        ----------
        parsed_content: :class:`bs4.Tag`
            The parsed content of the page.

        Returns
        -------
        :class:`bool`
            Whether the logo was found or not.
        """
        logo_img = parsed_content.find('img', {'height': '64'})
        if logo_img is None:
            return False

        self.logo_url = logo_img["src"]
        return True

    def _parse_guild_members(self, parsed_content):
        """
        Parses the guild's member and invited list.

        Parameters
        ----------
        parsed_content: :class:`bs4.Tag`
            The parsed content of the guild's page
        """
        member_rows = parsed_content.find_all("tr", {'bgcolor': ["#D4C0A1", "#F1E0C6"]})
        previous_rank = {}
        for row in member_rows:
            columns = row.find_all('td')
            values = tuple(c.text.replace("\u00a0", " ") for c in columns)
            if len(columns) == COLS_GUILD_MEMBER:
                self._parse_current_member(previous_rank, values)
            if len(columns) == COLS_INVITED_MEMBER:
                self._parse_invited_member(values)

    def _parse_invited_member(self, values):
        """
        Parses the column texts of an invited row into a invited dictionary.

        Parameters
        ----------
        values: tuple[:class:`str`]
            A list of row contents.
        """
        name, date = values
        if date != "Invitation Date":
            self.invites.append(GuildInvite(name, date))
    # endregion


class GuildMember(abc.BaseCharacter):
    """
    Represents a guild member.

    Attributes
    --------------
    rank: :class:`str`
        The rank the member belongs to
    name: :class:`str`
        The name of the guild member.
    title: :class:`str`, optional
        The member's title.
    level: :class:`int`
        The member's level.
    vocation: :class:`.Vocation`
        The member's vocation.
    joined: :class:`datetime.date`
        The day the member joined the guild.
    online: :class:`bool`
        Whether the member is online or not.
    """
    __slots__ = ("name", "rank", "title", "level", "vocation", "joined", "online")

    def __init__(self, name=None, rank=None, title=None, level=0, vocation=None, **kwargs):
        self.name = name
        self.rank = rank
        self.title = title
        self.vocation = try_enum(Vocation, vocation)
        self.level = level
        joined = kwargs.get("joined")
        self.online = kwargs.get("online")
        if isinstance(joined, datetime.datetime):
            self.joined = joined.date()
        elif isinstance(joined, datetime.date):
            self.joined = joined
        elif isinstance(joined, str):
            self.joined = parse_tibia_date(joined)
        else:
            self.joined = None


class GuildInvite(abc.BaseCharacter):
    """Represents an invited character

    Attributes
    ------------
    name: :class:`str`
        The name of the character

    date: :class:`datetime.date`
        The day when the character was invited.
    """
    __slots__ = ("date", )

    def __init__(self, name=None, date=None):
        self.name = name
        if isinstance(date, datetime.datetime):
            self.date = date.date()
        elif isinstance(date, datetime.date):
            self.date = date
        elif isinstance(date, str):
            self.date = parse_tibia_date(date)
        else:
            self.date = None

    def __repr__(self):
        return "<{0.__class__.__name__} name={0.name!r} " \
               "date={0.date!r}>".format(self)


class ListedGuild(abc.BaseGuild):
    """
    Represents a Tibia guild in the guild list of a world.

    Attributes
    ------------
    name: :class:`str`
        The name of the guild.
    logo_url: :class:`str`
        The URL to the guild's logo.
    description: :class:`str`, optional
        The description of the guild.
    world: :class:`str`
        The world where this guild is in.
    active: :class:`bool`
        Whether the guild is active or still in formation.
    """
    __slots__ = ("logo_url", "description", "world", "active")

    def __init__(self, name, world, logo_url=None, description=None, active=False):
        self.name = name
        self.world = world
        self.logo_url = logo_url
        self.description = description
        self.active = active

    # region Public methods
    @classmethod
    def get_world_list_url(cls, world):
        """Gets the Tibia.com URL for the guild section of a specific world.

        Parameters
        ----------
        world: :class:`str`
            The name of the world.

        Returns
        -------
        :class:`str`
            The URL to the guild's page
        """
        return GUILD_LIST_URL + urllib.parse.quote(world.title().encode('iso-8859-1'))

    @classmethod
    def get_world_list_url_tibiadata(cls, world):
        """Gets the TibiaData.com URL for the guild list of a specific world.

        Parameters
        ----------
        world: :class:`str`
            The name of the world.

        Returns
        -------
        :class:`str`
            The URL to the guild's page.
        """
        return GUILD_LIST_URL_TIBIADATA % urllib.parse.quote(world.title().encode('iso-8859-1'))

    @classmethod
    def list_from_content(cls, content, active_only=False):
        """
        Gets a list of guilds from the html content of the world guilds' page.

        The :class:`Guild` objects in the list only contain the attributes:
        :attr:`name`, :attr:`logo_url`, :attr:`world` and if available, :attr:`description`

        Parameters
        ----------
        content: :class:`str`
            The html content of the page.
        active_only: :class:`bool`
            Whether to only show active guilds or not.

        Returns
        -------
        List[:class:`Guild`]
            List of guilds in the current world.
        """
        guild_list = cls._parse_guild_list(content, active_only)
        if guild_list is None:
            return None
        return [cls(**g) for g in guild_list]

    @classmethod
    def list_from_tibiadata(cls, content) -> List['ListedGuild']:
        """Builds a character object from a TibiaData character response.
        Parameters
        ----------
        content: :class:`str`
            A string containing the JSON response from TibiaData.
        Returns
        -------
        :class:`list` of :class:`ListedGuild`
            The list of guilds contained.
        """
        try:
            json_content = json.loads(content)
        except json.JSONDecodeError:
            return None
        guilds_obj = json_content["guilds"]
        guilds = []
        for guild in guilds_obj["active"]:
            guilds.append(cls(guild["name"], guilds_obj["world"], logo_url=guild["guildlogo"],
                              description=guild["desc"], active=True))
        for guild in guilds_obj["formation"]:
            guilds.append(cls(guild["name"], guilds_obj["world"], logo_url=guild["guildlogo"],
                              description=guild["desc"], active=False))

        return guilds
    # endregion

    # region Private methods
    @classmethod
    def _parse_guild_list(cls, content, active_only=False):
        """
        Parses the contents of a world's guild list page.

        Parameters
        ----------
        content: :class:`str`
            The HTML content of the page.
        active_only: :class:`bool`
            Whether to only show active guilds.

        Returns
        -------
        List[:class:`dict`[str, Any]]
            A list of guild dictionaries.
        """
        parsed_content = bs4.BeautifulSoup(content.replace('ISO-8859-1', 'utf-8'), 'lxml',
                                           parse_only=bs4.SoupStrainer("div", class_="BoxContent"))
        selected_world = parsed_content.find('option', selected=True)
        try:
            if "choose world" in selected_world.text:
                return None
            world = selected_world.text
        except AttributeError:
            raise InvalidContent("Content does not belong to world guild list.")
        containers = parsed_content.find_all('div', class_="TableContainer")
        try:
            # First TableContainer contains world selector.
            containers = containers[1:]
        except IndexError:
            raise InvalidContent("Content does not belong to world guild list.")
        guilds = []
        for container in containers:
            header = container.find('div', class_="Text")
            active = "Active" in header.text
            if active_only and not active:
                return guilds
            header, *rows = container.find_all("tr", {'bgcolor': ["#D4C0A1", "#F1E0C6"]})
            for row in rows:
                columns = row.find_all('td')
                logo_img = columns[0].find('img')["src"]
                description_lines = columns[1].get_text("\n").split("\n", 1)
                name = description_lines[0]
                description = None
                if len(description_lines) > 1:
                    description = description_lines[1].replace("\r", "").replace("\n", " ")
                guilds.append({"logo_url": logo_img, "name": name, "description": description, "active": active,
                               "world": world})
        return guilds
    # endregion
