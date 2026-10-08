import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

os.environ.setdefault('GROQ_API_KEY', 'test-key')


@pytest.fixture(scope='session')
def real_sms_xml():
    explicit = os.getenv('PESAPILOT_SMS_XML')
    candidates = [explicit] if explicit else sorted(glob.glob(os.path.join(ROOT, 'data', 'raw', '*.xml')))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    pytest.skip("No SMS backup XML found. Put one in data/raw/ or set PESAPILOT_SMS_XML.")


@pytest.fixture(scope='session')
def real_transactions(real_sms_xml):
    from src.parse_sms import MpesaParser
    return MpesaParser().parse_xml_to_csv(real_sms_xml)
