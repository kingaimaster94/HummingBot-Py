import asyncio
import json
import re
import time
import unittest
from typing import Awaitable
from unittest.mock import AsyncMock, MagicMock, patch

from aioresponses import aioresponses

from hummingbot.connector.test_support.network_mocking_assistant import NetworkMockingAssistant
from hummingbot.data_feed.candles_feed.gate_io_perpetual_candles import GateioPerpetualCandles, constants as CONSTANTS


class TestGateioPerpetualCandles(unittest.TestCase):
    # the level is required to receive logs from the data source logger
    level = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ev_loop = asyncio.get_event_loop()
        cls.base_asset = "BTC"
        cls.quote_asset = "USDT"
        cls.interval = "1h"
        cls.trading_pair = f"{cls.base_asset}-{cls.quote_asset}"
        cls.ex_trading_pair = cls.base_asset + "_" + cls.quote_asset
        cls.quanto_multiplier = 0.0001

    def setUp(self) -> None:
        super().setUp()
        self.mocking_assistant = NetworkMockingAssistant()
        self.data_feed = GateioPerpetualCandles(trading_pair=self.trading_pair, interval=self.interval)
        self.data_feed.quanto_multiplier = 0.0001

        self.log_records = []
        self.data_feed.logger().setLevel(1)
        self.data_feed.logger().addHandler(self)
        self.resume_test_event = asyncio.Event()

    def handle(self, record):
        self.log_records.append(record)

    def is_logged(self, log_level: str, message: str) -> bool:
        return any(
            record.levelname == log_level and record.getMessage() == message for
            record in self.log_records)

    def async_run_with_timeout(self, coroutine: Awaitable, timeout: int = 1):
        ret = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(coroutine, timeout))
        return ret

    def get_candles_rest_data_mock(self):
        data = [
            {
                "t": 1685167200,
                "v": 97151,
                "c": "1.032",
                "h": "1.032",
                "l": "1.032",
                "o": "1.032",
                "sum": "3580"
            }, {
                "t": 1685167300,
                "v": 97151,
                "c": "1.032",
                "h": "1.032",
                "l": "1.032",
                "o": "1.032",
                "sum": "3580"
            }, {
                "t": 1685167400,
                "v": 97151,
                "c": "1.032",
                "h": "1.032",
                "l": "1.032",
                "o": "1.032",
                "sum": "3580"
            }, {
                "t": 1685172600,
                "v": 97151,
                "c": "1.032",
                "h": "1.032",
                "l": "1.032",
                "o": "1.032",
                "sum": "3580"
            },
        ]
        return data

    def get_exchange_trading_pair_quanto_multiplier_data_mock(self):
        data = {"quanto_multiplier": 0.0001}
        return data

    def get_candles_ws_data_mock_1(self):
        data = {
            "time": 1542162490,
            "time_ms": 1542162490123,
            "channel": "futures.candlesticks",
            "event": "update",
            "error": None,
            "result": [
                {
                    "t": 1545129300,
                    "v": 27525555,
                    "c": "95.4",
                    "h": "96.9",
                    "l": "89.5",
                    "o": "94.3",
                    "n": "1m_BTC_USD"
                }
            ]
        }
        return data

    def get_candles_ws_data_mock_2(self):
        data = {
            "time": 1542162490,
            "time_ms": 1542162490123,
            "channel": "futures.candlesticks",
            "event": "update",
            "error": None,
            "result": [
                {
                    "t": 1545139300,
                    "v": 27525555,
                    "c": "95.4",
                    "h": "96.9",
                    "l": "89.5",
                    "o": "94.3",
                    "n": "1m_BTC_USD"
                }
            ]
        }
        return data

    @aioresponses()
    def test_fetch_candles(self, mock_api: aioresponses):
        start_time = 1685167200
        end_time = 1685172600
        url = f"{CONSTANTS.REST_URL}{CONSTANTS.CANDLES_ENDPOINT}"
        regex_url = re.compile(f"^{url}".replace(".", r"\.").replace("?", r"\?"))
        data_mock = self.get_candles_rest_data_mock()
        mock_api.get(url=regex_url, body=json.dumps(data_mock))

        resp = self.async_run_with_timeout(self.data_feed.fetch_candles(start_time=start_time, end_time=end_time))

        self.assertEqual(resp.shape[0], len(data_mock))
        self.assertEqual(resp.shape[1], 10)

    @aioresponses()
    def test_get_exchange_trading_pair_quanto_multiplier(self, mock_api: aioresponses):
        url = CONSTANTS.REST_URL + CONSTANTS.CONTRACT_INFO_URL.format(contract=self.ex_trading_pair)
        regex_url = re.compile(f"^{url}".replace(".", r"\.").replace("?", r"\?"))
        data_mock = self.get_exchange_trading_pair_quanto_multiplier_data_mock()
        mock_api.get(url=regex_url, body=json.dumps(data_mock))
        resp = self.async_run_with_timeout(self.data_feed.get_exchange_trading_pair_quanto_multiplier())

        self.assertEqual(resp, 0.0001)

    def test_candles_empty(self):
        self.assertTrue(self.data_feed.candles_df.empty)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    def test_listen_for_subscriptions_subscribes_to_klines(self, ws_connect_mock):
        ws_connect_mock.return_value = self.mocking_assistant.create_websocket_mock()

        result_subscribe_klines = {
            "result": None,
            "id": 1
        }

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value,
            message=json.dumps(result_subscribe_klines))

        self.listening_task = self.ev_loop.create_task(self.data_feed.listen_for_subscriptions())

        self.mocking_assistant.run_until_all_aiohttp_messages_delivered(ws_connect_mock.return_value)

        sent_subscription_messages = self.mocking_assistant.json_messages_sent_through_websocket(
            websocket_mock=ws_connect_mock.return_value)

        self.assertEqual(1, len(sent_subscription_messages))
        expected_kline_subscription = {
            "time": int(time.time()),
            "channel": CONSTANTS.WS_CANDLES_ENDPOINT,
            "event": "subscribe",
            "payload": [self.interval, self.ex_trading_pair]
        }
        self.assertEqual(expected_kline_subscription["channel"], sent_subscription_messages[0]["channel"])
        self.assertEqual(expected_kline_subscription["payload"], sent_subscription_messages[0]["payload"])

        self.assertTrue(self.is_logged(
            "INFO",
            "Subscribed to public klines..."
        ))

    @patch("hummingbot.data_feed.candles_feed.gate_io_perpetual_candles.GateioPerpetualCandles._sleep")
    @patch("aiohttp.ClientSession.ws_connect")
    def test_listen_for_subscriptions_raises_cancel_exception(self, mock_ws, _: AsyncMock):
        mock_ws.side_effect = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            self.listening_task = self.ev_loop.create_task(self.data_feed.listen_for_subscriptions())
            self.async_run_with_timeout(self.listening_task)

    @patch("hummingbot.data_feed.candles_feed.gate_io_perpetual_candles.GateioPerpetualCandles._sleep")
    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    def test_listen_for_subscriptions_logs_exception_details(self, mock_ws, sleep_mock: AsyncMock):
        mock_ws.side_effect = Exception("TEST ERROR.")
        sleep_mock.side_effect = lambda _: self._create_exception_and_unlock_test_with_event(
            asyncio.CancelledError())

        self.listening_task = self.ev_loop.create_task(self.data_feed.listen_for_subscriptions())

        self.async_run_with_timeout(self.resume_test_event.wait())

        self.assertTrue(
            self.is_logged(
                "ERROR",
                "Unexpected error occurred when listening to public klines. Retrying in 1 seconds..."))

    def test_subscribe_channels_raises_cancel_exception(self):
        mock_ws = MagicMock()
        mock_ws.send.side_effect = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            self.listening_task = self.ev_loop.create_task(self.data_feed._subscribe_channels(mock_ws))
            self.async_run_with_timeout(self.listening_task)

    def test_subscribe_channels_raises_exception_and_logs_error(self):
        mock_ws = MagicMock()
        mock_ws.send.side_effect = Exception("Test Error")

        with self.assertRaises(Exception):
            self.listening_task = self.ev_loop.create_task(self.data_feed._subscribe_channels(mock_ws))
            self.async_run_with_timeout(self.listening_task)

        self.assertTrue(
            self.is_logged("ERROR", "Unexpected error occurred subscribing to public klines...")
        )

    @patch("hummingbot.data_feed.candles_feed.gate_io_perpetual_candles.GateioPerpetualCandles.fill_historical_candles", new_callable=AsyncMock)
    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    def test_process_websocket_messages_empty_candle(self, ws_connect_mock, fill_historical_candles_mock):
        ws_connect_mock.return_value = self.mocking_assistant.create_websocket_mock()

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value,
            message=json.dumps(self.get_candles_ws_data_mock_1()))

        self.listening_task = self.ev_loop.create_task(self.data_feed.listen_for_subscriptions())

        self.mocking_assistant.run_until_all_aiohttp_messages_delivered(ws_connect_mock.return_value)

        self.assertEqual(self.data_feed.candles_df.shape[0], 1)
        self.assertEqual(self.data_feed.candles_df.shape[1], 10)
        fill_historical_candles_mock.assert_called_once()

    @patch("hummingbot.data_feed.candles_feed.gate_io_perpetual_candles.GateioPerpetualCandles.fill_historical_candles",
           new_callable=AsyncMock)
    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    def test_process_websocket_messages_duplicated_candle_not_included(self, ws_connect_mock, fill_historical_candles):
        ws_connect_mock.return_value = self.mocking_assistant.create_websocket_mock()
        fill_historical_candles.return_value = None

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value,
            message=json.dumps(self.get_candles_ws_data_mock_1()))

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value,
            message=json.dumps(self.get_candles_ws_data_mock_1()))

        self.listening_task = self.ev_loop.create_task(self.data_feed.listen_for_subscriptions())

        self.mocking_assistant.run_until_all_aiohttp_messages_delivered(ws_connect_mock.return_value)

        self.assertEqual(self.data_feed.candles_df.shape[0], 1)
        self.assertEqual(self.data_feed.candles_df.shape[1], 10)

    @patch("hummingbot.data_feed.candles_feed.gate_io_perpetual_candles.GateioPerpetualCandles.fill_historical_candles")
    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    def test_process_websocket_messages_with_two_valid_messages(self, ws_connect_mock, _):
        ws_connect_mock.return_value = self.mocking_assistant.create_websocket_mock()

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value,
            message=json.dumps(self.get_candles_ws_data_mock_1()))

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=ws_connect_mock.return_value,
            message=json.dumps(self.get_candles_ws_data_mock_2()))

        self.listening_task = self.ev_loop.create_task(self.data_feed.listen_for_subscriptions())

        self.mocking_assistant.run_until_all_aiohttp_messages_delivered(ws_connect_mock.return_value, timeout=2)

        self.assertEqual(self.data_feed.candles_df.shape[0], 2)
        self.assertEqual(self.data_feed.candles_df.shape[1], 10)

    def _create_exception_and_unlock_test_with_event(self, exception):
        self.resume_test_event.set()
        raise exception
