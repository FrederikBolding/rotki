import datetime
import json
from copy import deepcopy
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from rotkehlchen.accounting.structures.balance import Balance
from rotkehlchen.assets.resolver import AssetResolver
from rotkehlchen.chain.ethereum.airdrops import (
    AIRDROPS_INDEX,
    AIRDROPS_REPO_BASE,
    ETAG_CACHE_KEY,
    _parse_airdrops,
    check_airdrops,
    fetch_airdrops_metadata,
)
from rotkehlchen.chain.evm.types import string_to_evm_address
from rotkehlchen.constants.assets import A_1INCH, A_GRAIN, A_SHU, A_UNI
from rotkehlchen.constants.misc import AIRDROPSDIR_NAME, AIRDROPSPOAPDIR_NAME, APPDIR_NAME
from rotkehlchen.constants.timing import HOUR_IN_SECONDS
from rotkehlchen.db.history_events import DBHistoryEvents
from rotkehlchen.errors.misc import RemoteError
from rotkehlchen.fval import FVal
from rotkehlchen.globaldb.cache import (
    globaldb_get_unique_cache_value,
    globaldb_set_unique_cache_value,
)
from rotkehlchen.globaldb.handler import GlobalDBHandler
from rotkehlchen.history.events.structures.evm_event import EvmEvent
from rotkehlchen.history.events.structures.types import HistoryEventSubType, HistoryEventType
from rotkehlchen.tests.utils.factories import make_evm_tx_hash
from rotkehlchen.types import CacheType, Location, TimestampMS
from rotkehlchen.utils.serialization import rlk_jsondumps

TEST_ADDR1 = string_to_evm_address('0x2B888954421b424C5D3D9Ce9bB67c9bD47537d12')
TEST_ADDR2 = string_to_evm_address('0x51985CE8BB9AB1708746b24e22e37CD7A980Ec24')
TEST_POAP1 = string_to_evm_address('0x043e2a6047e50710e0f5189DBA7623C4A183F871')
NOT_CSV_WEBPAGE = {
    'airdrops': {
        'test': {
            'csv_path': 'notavalidpath/yabirgb',
            'csv_hash': 'd39fdc7913b4cbafc90cd0458c9e88656e951d9c216a9f4c0e973b7e7c6f1882',
            'asset_identifier': 'eip155:1/erc20:0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984',
            'url': 'https://github.com',
            'name': 'Yabirgb',
            'icon': 'yabirgb.png',
        },
    }, 'poap_airdrops': {},
}
MOCK_AIRDROP_INDEX = {'airdrops': {
    'uniswap': {
        'csv_path': 'airdrops/uniswap.csv',
        'csv_hash': '87c81b0070d4a19ab87fd631b79247293031412706ec5414a859899572470ddf',
        'asset_identifier': 'eip155:1/erc20:0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984',
        'url': 'https://app.uniswap.org/',
        'name': 'Uniswap',
        'icon': 'uniswap.svg',
    },
    '1inch': {
        'csv_path': 'airdrops/1inch.csv',
        'csv_hash': '7f8a67b1fe7c2019bcac956777d306dd372ebe5bc2a9cd920129884170562108',
        'asset_identifier': 'eip155:1/erc20:0x111111111117dC0aa78b770fA6A738034120C302',
        'url': 'https://1inch.exchange/',
        'name': '1inch',
        'icon': '1inch.svg',
    },
    'grain': {
        'csv_path': 'airdrops/grain_iou.csv',
        'csv_hash': 'dff6b525931ac7ad321efd8efc419370a9d7a222e92b1aad7a985b7e61248121',
        'asset_identifier': 'eip155:1/erc20:0x6589fe1271A0F29346796C6bAf0cdF619e25e58e',
        'url': 'https://claim.harvest.finance/',
        'name': 'Grain',
        'icon': 'grain.png',
        'icon_path': 'airdrops/icons/grain.svg',
    },
    'shapeshift': {
        'csv_path': 'airdrops/shapeshift.csv',
        'csv_hash': '97b599c62af4391a19c17b47bd020733801e28a443443ad7e1602c647c9ebfe2',
        'asset_identifier': 'eip155:1/erc20:0xc770EEfAd204B5180dF6a14Ee197D99d808ee52d',
        'url': 'https://shapeshift.com/shapeshift-decentralize-airdrop',
        'name': 'ShapeShift',
        'icon': 'shapeshift.svg',
    },
    'cow_gnosis': {
        'csv_path': 'airdrops/cow_gnosis.csv',
        'csv_hash': 'f7fea2a5806c67a27c15bb4e05c3fd6c0c1ab51f5bd2a23c29852fa2f95a7db3',
        'asset_identifier': 'eip155:100/erc20:0xc20C9C13E853fc64d054b73fF21d3636B2d97eaB',
        'url': 'https://cowswap.exchange/#/claim',
        'name': 'COW (gnosis chain)',
        'icon': 'cow.svg',
    },
    'diva': {
        'csv_path': 'airdrops/diva.csv',
        'csv_hash': '50cf9f2bb2f769ae20dc699809b8bdca5f48ce695c792223ad93f8681ab8d0fc',
        'asset_identifier': 'eip155:1/erc20:0xBFAbdE619ed5C4311811cF422562709710DB587d',
        'url': 'https://claim.diva.community/',
        'name': 'DIVA',
        'icon': 'diva.svg',
    },
    'shutter': {
        'csv_path': 'airdrops/shutter.csv',
        'csv_hash': 'd4427f41181803df49901241ec89ed6a235b8b67cc4ef5cfdef1515dc84704d1',
        'asset_identifier': 'eip155:1/erc20:0xe485E2f1bab389C08721B291f6b59780feC83Fd7',
        'url': 'https://claim.shutter.network/',
        'name': 'SHU',
        'icon': 'shutter.png',
        'cutoff_time': 1721000000,
    },
    'invalid': {
        'csv_path': 'airdrops/invalid.csv',
        'csv_hash': 'a426abd9f7af3ec3138fe393e4735129a5884786b7bbda8de30002c134951aec',
        'asset_identifier': 'eip155:1/erc20:0xe485E2f1bab389C08721B291f6b59780feC83Fd7',
        'url': 'https://claim.invalid.community/',
        'name': 'INVALID',
        'icon': 'invalid.svg',
    },
}, 'poap_airdrops': {
    'aave_v2_pioneers': [
        'airdrops/poap/poap_aave_v2_pioneers.json',
        'https://poap.delivery/aave-v2-pioneers',
        'AAVE V2 Pioneers',
        '388003b6c0dc589981ce9e962d6d8b6b2148c72ccf6ec3578ab32d63b547f903',
    ],
}}


def _mock_airdrop_list(url: str, timeout: int = 0, headers: dict | None = None):  # pylint: disable=unused-argument
    mock_response = Mock()
    if url == AIRDROPS_INDEX:
        mock_response.headers = {'ETag': 'etag'}
        mock_response.text = json.dumps(NOT_CSV_WEBPAGE)
        mock_response.json = lambda: NOT_CSV_WEBPAGE
        return mock_response
    else:  # when CSV is queried, return invalid payload
        mock_response.text = mock_response.content = '<>invalid CSV<>'
        return mock_response


@pytest.mark.freeze_time()
@pytest.mark.parametrize('number_of_eth_accounts', [2])
@pytest.mark.parametrize('use_clean_caching_directory', [True])
@pytest.mark.parametrize('new_asset_data', [{
    'asset_type': 'EVM_TOKEN',  # test with EVM token
    'address': '0xe485E2f1bab389C08721B291f6b59780feC83Fd7',
    'name': 'Shutter',
    'symbol': 'SHU',
    'chain_id': 1,
    'decimals': 18,
    'coingecko': 'shutter',
    'cryptocompare': 'SHUTTER',
}, {
    'asset_type': 'SOLANA_TOKEN',  # test with non EVM token
    'name': 'Some Non EVM Token',
    'symbol': 'NONEVM',
    'coingecko': 'nonevm',
    'cryptocompare': 'NONEVM',
}])
@pytest.mark.parametrize('remove_global_assets', [['eip155:1/erc20:0xe485E2f1bab389C08721B291f6b59780feC83Fd7']])  # noqa: E501
def test_check_airdrops(
        freezer,
        ethereum_accounts,
        database,
        globaldb,
        new_asset_data,
        data_dir,
        messages_aggregator,
):
    # create airdrop claim events to test the claimed attribute
    tolerance_for_amount_check = FVal('0.1')
    claim_events = [
        EvmEvent(
            tx_hash=make_evm_tx_hash(),
            sequence_index=0,
            timestamp=TimestampMS(1594500575000),
            location=Location.ETHEREUM,
            event_type=HistoryEventType.RECEIVE,
            event_subtype=HistoryEventSubType.AIRDROP,
            asset=A_UNI,
            balance=Balance(amount=FVal('400') + tolerance_for_amount_check * FVal('0.25')),  # inside tolerance  # noqa: E501
            location_label=string_to_evm_address(TEST_ADDR1),
        ), EvmEvent(
            tx_hash=make_evm_tx_hash(),
            sequence_index=0,
            timestamp=TimestampMS(1594500575000),
            location=Location.ETHEREUM,
            event_type=HistoryEventType.RECEIVE,
            event_subtype=HistoryEventSubType.AIRDROP,
            asset=A_1INCH,
            balance=Balance(amount=FVal('630.374421472277638654') + tolerance_for_amount_check * FVal('2')),  # outside tolerance  # noqa: E501
            location_label=string_to_evm_address(TEST_ADDR1),
        ),
    ]
    MOCK_AIRDROP_INDEX['airdrops']['shutter']['new_asset_data'] = new_asset_data
    mock_airdrop_index = deepcopy(MOCK_AIRDROP_INDEX)

    new_asset_identifier = MOCK_AIRDROP_INDEX['airdrops']['shutter']['asset_identifier']
    AssetResolver.assets_cache.clear()  # remove new asset from cache

    events_db = DBHistoryEvents(database)
    with database.conn.write_ctx() as write_cursor:
        events_db.add_history_events(write_cursor, claim_events)

    def _prepare_mock_response(url: str, update_airdrop_index: bool = False):
        """Mocking the airdrop data is very convenient here because the airdrop data is quite large
        and read timeout errors can happen even with 90secs threshold. Vcr-ing it is not possible
        because the vcr yaml file is above the github limit of 100MB. The schema of AIRDROPS_INDEX
        is checked in the rotki/data repo."""
        mock_response = Mock()
        if update_airdrop_index is True:
            mock_airdrop_index['airdrops']['diva']['csv_hash'] = 'updated_hash'
            mock_airdrop_index['poap_airdrops']['aave_v2_pioneers'][3] = 'updated_hash'
            mock_response.headers = {'ETag': 'updated_etag'}
        url_to_data_map = {
            AIRDROPS_INDEX: mock_airdrop_index,
            f'{AIRDROPS_REPO_BASE}/airdrops/uniswap.csv':
                f'address,uni,is_lp,is_user,is_socks\n{TEST_ADDR1},400,False,True,False\n{TEST_ADDR2},400.050642,True,True,False\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/1inch.csv':
                f'address,tokens\n{TEST_ADDR1},630.374421472277638654\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/shapeshift.csv':
                f'address,tokens\n{TEST_ADDR1},200\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/cow_gnosis.csv':
                f'address,tokens\n{TEST_ADDR1},99807039723201809834\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/diva.csv':
                f'address,tokens\n{TEST_ADDR1},84000\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/grain_iou.csv':
                f'address,tokens\n{TEST_ADDR2},16301717650649890035791\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/shutter.csv':
                f'address,tokens\n{TEST_ADDR2},394857.029384576349787465\n',
            f'{AIRDROPS_REPO_BASE}/airdrops/invalid.csv':
                f'address,tokens\n{TEST_ADDR2},123\n{TEST_ADDR2},123\n\n',  # will be skipped because last row is empty  # noqa: E501
            f'{AIRDROPS_REPO_BASE}/airdrops/poap/poap_aave_v2_pioneers.json':
                f'{{"{TEST_POAP1}": [\n566\n]}}',
        }
        if url == AIRDROPS_INDEX:
            mock_response.text = json.dumps(mock_airdrop_index)
            mock_response.json = lambda: mock_airdrop_index
            mock_response.headers = {'ETag': 'etag'}
        else:
            mock_response.text = url_to_data_map.get(url, 'address,tokens\n')  # Return the data from the dictionary or just a header if 'url' is not found  # noqa: E501
            assert isinstance(mock_response.text, str)
            mock_response.content = mock_response.text.encode('utf-8')
        return mock_response

    def mock_requests_get(url: str, timeout: int = 0, headers: dict | None = None):  # pylint: disable=unused-argument
        return _prepare_mock_response(url)

    # invalid metadata index is already present
    with globaldb.conn.write_ctx() as write_cursor:
        globaldb_set_unique_cache_value(
            write_cursor=write_cursor,
            key_parts=(CacheType.AIRDROPS_METADATA,),
            value='{"metadata": "invalid"}',
        )

    # no CSV hashes are present in the DB
    with globaldb.conn.read_ctx() as cursor:
        assert cursor.execute(
            'SELECT COUNT(*) FROM unique_cache WHERE key LIKE ?', ('AIRDROPS_HASH%',),
        ).fetchone()[0] == 0

    # one CSV is already present with invalid content, but no cached hash in DB
    csv_dir = data_dir / APPDIR_NAME / AIRDROPSDIR_NAME
    csv_dir.mkdir(parents=True, exist_ok=True)
    with open(csv_dir / 'shapeshift.csv', 'w', encoding='utf8') as f:
        f.write('invalid,csv\n')

    # testing just on the cutoff time of shutter
    freezer.move_to(datetime.datetime.fromtimestamp(1721000000, tz=datetime.UTC))
    with (
        patch('rotkehlchen.chain.ethereum.airdrops.SMALLEST_AIRDROP_SIZE', 1),
        patch('rotkehlchen.chain.ethereum.airdrops.requests.get', side_effect=mock_requests_get),
        patch('rotkehlchen.globaldb.handler.GlobalDBHandler.packaged_db_conn', side_effect=lambda: GlobalDBHandler().conn),  # not using packaged DB to ensure that new tokens are created  # noqa: E501
    ):
        with GlobalDBHandler().conn.read_ctx() as cursor:
            assert cursor.execute(
                'SELECT COUNT(*) FROM assets WHERE identifier=?',
                (new_asset_identifier,),
            ).fetchone()[0] == 0  # asset not present before
        data = check_airdrops(
            msg_aggregator=messages_aggregator,
            addresses=ethereum_accounts + [TEST_ADDR1, TEST_ADDR2, TEST_POAP1],
            database=database,
            data_dir=data_dir,
            tolerance_for_amount_check=tolerance_for_amount_check,
        )

    # invalid metadata index is replaced by the valid one
    with globaldb.conn.read_ctx() as cursor:
        assert globaldb_get_unique_cache_value(
            cursor=cursor,
            key_parts=(CacheType.AIRDROPS_METADATA,),
        ) == json.dumps(MOCK_AIRDROP_INDEX)

    # new CSV hashes are saved in the DB
    with globaldb.conn.read_ctx() as cursor:
        assert cursor.execute(
            'SELECT COUNT(*) FROM unique_cache WHERE key LIKE ?', ('AIRDROPS_HASH%',),
        ).fetchone()[0] == 10
        assert cursor.execute(
            'SELECT value FROM unique_cache WHERE key=?', ('AIRDROPS_HASHdiva.csv',),
        ).fetchone()[0] == MOCK_AIRDROP_INDEX['airdrops']['diva']['csv_hash']

    # invalid CSV is also, updated
    assert (csv_dir / 'shapeshift.csv').read_text(encoding='utf8') == f'address,tokens\n{TEST_ADDR1},200\n'  # noqa: E501

    # verify new asset's presence and details
    new_found_asset = AssetResolver.resolve_asset(new_asset_identifier).resolve_to_crypto_asset()
    assert new_found_asset.name == new_asset_data['name']
    assert new_found_asset.symbol == new_asset_data['symbol']
    assert new_found_asset.coingecko == new_asset_data['coingecko']
    assert new_found_asset.cryptocompare == new_asset_data['cryptocompare']

    # Test data is returned for the address correctly
    assert len(data) == 3
    assert len(data[TEST_ADDR1]) == 5
    assert data[TEST_ADDR1]['uniswap'] == {
        'amount': '400',
        'asset': A_UNI,
        'link': 'https://app.uniswap.org/',
        'claimed': True,
    }
    assert data[TEST_ADDR1]['1inch'] == {
        'amount': '630.374421472277638654',
        'asset': A_1INCH,
        'link': 'https://1inch.exchange/',
        'claimed': False,
    }
    assert messages_aggregator.warnings[0] == 'Skipping airdrop CSV for invalid because it contains an invalid row: []'  # noqa: E501

    assert len(data[TEST_ADDR2]) == 3
    assert data[TEST_ADDR2]['uniswap'] == {
        'amount': '400.050642',
        'asset': A_UNI,
        'link': 'https://app.uniswap.org/',
        'claimed': False,
    }
    assert data[TEST_ADDR2]['grain'] == {
        'amount': '16301.717650649890035791',
        'asset': A_GRAIN,
        'link': 'https://claim.harvest.finance/',
        'claimed': False,
        'icon_url': f'{AIRDROPS_REPO_BASE}/airdrops/icons/grain.svg',
    }
    assert data[TEST_ADDR2]['shutter'] == {
        'amount': '394857.029384576349787465',
        'asset': A_SHU,
        'link': 'https://claim.shutter.network/',
        'claimed': False,
    }
    assert len(data[TEST_POAP1]) == 1
    assert data[TEST_POAP1]['poap'] == [{
        'event': 'aave_v2_pioneers',
        'assets': [566],
        'link': 'https://poap.delivery/aave-v2-pioneers',
        'name': 'AAVE V2 Pioneers',
    }]

    # after cutoff time of shutter
    freezer.move_to(datetime.datetime.fromtimestamp(1721000001, tz=datetime.UTC))
    with (
        patch('rotkehlchen.chain.ethereum.airdrops.SMALLEST_AIRDROP_SIZE', 1),
        patch('rotkehlchen.chain.ethereum.airdrops.requests.get', side_effect=mock_requests_get) as mock_get,  # noqa: E501
    ):
        data = check_airdrops(
            msg_aggregator=messages_aggregator,
            addresses=[TEST_ADDR2],
            database=database,
            data_dir=data_dir,
            tolerance_for_amount_check=tolerance_for_amount_check,
        )
        assert mock_get.call_count == 1
    assert len(data[TEST_ADDR2]) == 2
    assert 'shutter' not in data[TEST_ADDR2]

    def update_mock_requests_get(url: str, timeout: int = 0, headers: dict | None = None):  # pylint: disable=unused-argument
        return _prepare_mock_response(url, update_airdrop_index=True)

    freezer.move_to(datetime.datetime.fromtimestamp(1721000001 + 12 * HOUR_IN_SECONDS, tz=datetime.UTC))  # noqa: E501
    with (
        patch('rotkehlchen.chain.ethereum.airdrops.SMALLEST_AIRDROP_SIZE', 1),
        patch('rotkehlchen.chain.ethereum.airdrops.requests.get', side_effect=update_mock_requests_get) as mock_get,  # noqa: E501
    ):
        data = check_airdrops(
            msg_aggregator=messages_aggregator,
            addresses=[TEST_ADDR2],
            database=database,
            data_dir=data_dir,
            tolerance_for_amount_check=tolerance_for_amount_check,
        )
        # diva CSV and aave JSON were queried again because their hashes were updated
        assert mock_get.call_count == 3

    # new CSV hashes are saved in the DB
    with globaldb.conn.read_ctx() as cursor:
        assert cursor.execute(
            'SELECT value FROM unique_cache WHERE key=?', ('AIRDROPS_HASHdiva.csv',),
        ).fetchone()[0] == 'updated_hash'

    # Test cache file and row is created
    for protocol_name in MOCK_AIRDROP_INDEX['airdrops']:
        assert (data_dir / APPDIR_NAME / AIRDROPSDIR_NAME / f'{protocol_name}.csv').is_file()
    for protocol_name in MOCK_AIRDROP_INDEX['poap_airdrops']:
        assert (data_dir / APPDIR_NAME / AIRDROPSPOAPDIR_NAME / f'{protocol_name}.json').is_file()
    with GlobalDBHandler().conn.read_ctx() as cursor:
        assert globaldb_get_unique_cache_value(
            cursor=cursor,
            key_parts=(CacheType.AIRDROPS_METADATA,),
        ) == rlk_jsondumps(mock_airdrop_index)


@pytest.mark.parametrize('use_clean_caching_directory', [True])
def test_airdrop_fail(database, data_dir, messages_aggregator):
    with (
        patch('rotkehlchen.chain.ethereum.airdrops.requests.get', side_effect=_mock_airdrop_list),
        pytest.raises(RemoteError),
    ):
        check_airdrops(
            msg_aggregator=messages_aggregator,
            addresses=[TEST_ADDR1],
            database=database,
            data_dir=data_dir,
        )


@pytest.mark.parametrize('remote_etag', ['etag', 'updated_etag'])
@pytest.mark.parametrize('database_etag', [None, 'etag', 'updated_etag'])
def test_fetch_airdrops_metadata(database, remote_etag, database_etag):
    if database_etag is not None:
        # if database_etag is present, add those values in DB
        with GlobalDBHandler().conn.write_ctx() as write_cursor:
            globaldb_set_unique_cache_value(
                write_cursor=write_cursor,
                key_parts=(CacheType.AIRDROPS_HASH, ETAG_CACHE_KEY),
                value=database_etag,
            )
            globaldb_set_unique_cache_value(
                write_cursor=write_cursor,
                key_parts=(CacheType.AIRDROPS_METADATA,),
                value=rlk_jsondumps(MOCK_AIRDROP_INDEX),
            )

    mock_airdrop_index = MOCK_AIRDROP_INDEX
    if remote_etag != database_etag:  # if etag is different, update mock_airdrop_index
        mock_airdrop_index['airdrops']['diva']['name'] = 'new_name'

    def _mock_get(url: str, timeout: int = 0, headers: dict | None = None):  # pylint: disable=unused-argument
        mock_response = Mock()
        mock_response.headers = {'ETag': remote_etag}
        if database_etag == remote_etag:  # not returning content in this case
            mock_response.status_code = HTTPStatus.NOT_MODIFIED
        else:
            mock_response.status_code = HTTPStatus.OK
            mock_response.text = rlk_jsondumps(mock_airdrop_index)
            mock_response.json = lambda: mock_airdrop_index
        return mock_response

    with patch('rotkehlchen.chain.ethereum.airdrops.requests.get', side_effect=_mock_get):
        metadata = fetch_airdrops_metadata(database)
        assert metadata == (
            _parse_airdrops(database=database, airdrops_data=mock_airdrop_index['airdrops']),
            mock_airdrop_index['poap_airdrops'],
        )
        if remote_etag != database_etag:  # check if the value is updated
            assert metadata[0]['diva'].name == 'new_name'
