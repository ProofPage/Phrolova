from app.core.utils import extract_youtube_id

def test_extract_youtube_id_variants():
    # 1) /live/ 형식
    assert extract_youtube_id("https://www.youtube.com/live/BQJSlMSIrPk") == "BQJSlMSIrPk"
    assert extract_youtube_id("https://www.youtube.com/live/kuisr7IcDGQ?feature=share") == "kuisr7IcDGQ"
    # 2) watch?v= 형식
    assert extract_youtube_id("https://www.youtube.com/watch?v=BQJSlMSIrPk") == "BQJSlMSIrPk"
    # 3) youtu.be 형식
    assert extract_youtube_id("https://youtu.be/BQJSlMSIrPk") == "BQJSlMSIrPk"
    # 4) @username 형식
    assert extract_youtube_id("https://www.youtube.com/@malwangtv") == "@malwangtv"
    assert extract_youtube_id("@malwangtv") == "@malwangtv"
    assert extract_youtube_id("malwangtv") == "@malwangtv"
    # 5) UC 채널 ID
    assert extract_youtube_id("UC-9-kyTE8y5JhEl5xWd-R4A") == "UC-9-kyTE8y5JhEl5xWd-R4A"
    assert extract_youtube_id("https://www.youtube.com/channel/UC-9-kyTE8y5JhEl5xWd-R4A") == "UC-9-kyTE8y5JhEl5xWd-R4A"
    # 6) @http 접두사가 붙은 비정상 입력
    assert extract_youtube_id("@https://www.youtube.com/live/BQJSlMSIrPk") == "BQJSlMSIrPk"
