# pylint: disable = no-member

import re
from datetime import datetime, time, timedelta
from textwrap import dedent
from typing import Union, Match

import requests
import discord
from discord import Embed
from discord.ext import tasks
from discord.ext.commands import Bot, GroupCog
from discord.app_commands import command, describe

from database.trivia import TriviaDB
from config import API
from utils.decorators import is_staff


class Trivia(GroupCog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.sent_today = False
        self.sent_date = None
        self.db: Union[TriviaDB, None] = None
        self.config: Union[dict, None] = None

    async def cog_load(self) -> None:
        self.db = TriviaDB(self.bot.pool)
        self.config = await self.db.get_config()
        self.trivia_loop.start()

    @staticmethod
    def _check_time(time_string: str) -> bool:
        """Checks if the time is valid.

        :param time_string: The time string. ex: 1:24, 16:23
        :return: True if the time is valid, False if not
        """

        pattern = r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$'
        return re.match(pattern, time_string) is not None

    def _get_schedule(self) -> time:
        """
        Gets the schedule of the trivia

        :return: Time
        """

        if self.config is None:  # If the config is None, return 00:00
            return time(0, 0)

        schedule_utc_plus_8 = datetime.strptime(
            self.config["schedule"],
            "%H:%M").time()  # Converts the schedule to a time object

        schedule_with_day = datetime.combine(
            datetime.today(),
            schedule_utc_plus_8)  # Combines the schedule with the current day

        schedule = schedule_with_day - timedelta(hours=8)  # Converts the schedule to UTC+0

        return schedule.time()

    @tasks.loop(minutes=1)
    async def trivia_loop(self) -> None:
        """
        The trivia loop that sends the trivia every day
        """

        if self.config is None:
            # If the config is None, return
            return

        if datetime.today().date() != self.sent_date:
            # If the current date is not equal to the sent_date, set sent_today to False
            self.sent_today = False

        if not datetime.utcnow().time() >= self._get_schedule():
            # If the current time is not greater than the schedule, return
            return

        if self.sent_today:
            # If the trivia has been sent today, return
            return

        trivia_channel = self.bot.get_channel(
            int(self.config["channel_id"])
        )  # Gets the trivia channel

        response = requests.get(
            "https://api.api-ninjas.com/v1/facts",
            headers={
                "X-Api-Key": API.api_ninja
            }
        )

        if response.status_code != 200:  # If the status code is not 200, return
            await trivia_channel.send(
                f"An error occurred while fetching trivia. Error code: {response.status_code}"
            )
            return

        response_json = response.json()

        embed = Embed(
            title="Prof. Progphil Trivia of the Day",
            description=response_json[0]["fact"],
            color=discord.Color.blurple()
        ).set_image(
            url="https://cdn.discordapp.com/attachments/972510204505763951/1076388478088122368/image-12.png"
        )

        await trivia_channel.send(embed=embed)

        self.sent_today = True
        self.sent_date = datetime.today().date()

    @trivia_loop.before_loop
    async def before_trivia_loop(self) -> None:
        await self.bot.wait_until_ready()

    @is_staff()
    @command(name="schedule", description="Schedule the trivia")
    @describe(schedule="Schedule of the trivia in 24 hour format ex. 12:00")
    async def schedule(self, interaction: discord.Interaction, schedule: str) -> None:
        """
        Schedules a trivia session

        :param interaction: Interaction
        :param schedule: Schedule of the trivia
        """

        if self.config is None:
            await interaction.response.send_message(
                "Please setup the trivia first, use /trivia setup.",
                ephemeral=True)
            return

        if self._check_time(schedule) is None:
            await interaction.response.send_message(
                "Please enter a correct time. 00:00 to 23:59",
                ephemeral=True
            )
            return

        await self.db.update(
            channel_id=self.config["channel_id"],
            schedule=schedule
        )  # Updates the config

        self.config = await self.db.get_config()  # Updates the config

        await interaction.response.send_message(
            f"Trivia session scheduled at {schedule}",
            ephemeral=True
        )

    @is_staff()
    @command(name="config", description="Get the trivia config")
    async def config(self, interaction: discord.Interaction) -> None:
        """
        Gets the trivia config

        :param interaction: Interaction
        """

        if self.config is None:
            await interaction.response.send_message(
                "Please setup the trivia first, use /trivia setup.",
                ephemeral=True)
            return

        embed = Embed(
            title="Trivia Config",
            description=dedent(f"""
                Channel: {
            self.bot.get_channel(
                int(self.config["channel_id"])
            ).mention
            }
                Schedule: {self.config["schedule"]}
            """),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @is_staff()
    @command(name="channel", description="Set the trivia channel")
    @describe(channel="Channel to send the trivia to")
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """
        Sets the trivia channel

        :param interaction: Interaction
        :param channel: Channel to send the trivia to
        """

        if self.config is None:
            await interaction.response.send_message(
                "Please setup the trivia first, use /trivia setup.",
                ephemeral=True)
            return

        await self.db.update(
            channel_id=channel.id,
            schedule=self.config["schedule"]
        )  # Updates the config

        self.config = await self.db.get_config()  # Updates the config

        await interaction.response.send_message(
            "Trivia channel set",
            ephemeral=True
        )

    @is_staff()
    @command(name="setup", description="Setup the trivia")
    @describe(channel="Channel to send the trivia to")
    @describe(schedule="Schedule of the trivia session in 24 hour format ex. 12:00")
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel, schedule: str) -> None:
        """
        Sets up the trivia

        :param interaction: Interaction
        :param channel: Channel to send the trivia to
        :param schedule: Schedule of the trivia
        """
        if self.config is not None:  # This makes that the trivia can only be setup once
            await interaction.response.send_message(
                "Trivia is already setup, use /trivia channel and /trivia schedule to change the channel and schedule.",
                ephemeral=True)
            return

        if self._check_time(schedule) is None:
            await interaction.response.send_message(
                "Please enter a correct time. 00:00 to 23:59",
                ephemeral=True
            )
            return

        await self.db.insert(
            channel_id=channel.id,
            schedule=schedule
        )  # Inserts the config

        self.config = await self.db.get_config()  # Updates the config

        await interaction.response.send_message(
            "Trivia setup",
            ephemeral=True
        )


async def setup(bot: Bot):
    await bot.add_cog(Trivia(bot))
