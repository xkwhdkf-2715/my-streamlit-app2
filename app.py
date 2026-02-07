import os
import json
import time
import requests
import streamlit as st
from openai import OpenAI

# =========================================================
# Page
# =========================================================
st.set_page_config(
    page_title="내가 선호하는 국내 여행지는?",
    page_icon="🧳",
    layout="wide"
)

# =========================================================
# Sidebar: API Keys
# =========================================================
st.sidebar.header("🔑 API 설정")

openai_key_input = st.sidebar.text_input("OpenAI API Key", type="password")
tour_key_input = st.sidebar.text_input("TourAPI ServiceKey", type="password")

st.sidebar.caption("OpenAI 키 + 한국관광공사 TourAPI 키를 입력해야 추천이 작동해요.")

# 환경 변수 fallback
openai_key_env = os.getenv("OPENAI_API_KEY", "")
tour_key_env = os.getenv("TOUR_API_KEY", "")

OPENAI_API_KEY = openai_key_input if openai_key_input else openai_key_env
TOUR_API_KEY = tour_key_input if tour_key_input else tour_key_env

# =========================================================
# TourAPI Constants
# =========================================================
TOUR_BASE = "https://apis.data.go.kr/B551011/KorService2"

# contentTypeId
CONTENT_TYPE_TOUR = 12  # 관광지

# =========================================================
# UI Header
# =========================================================
st.title("내가 선호하는 국내 여행지는?")
st.caption("선호도 조사 + 추가 입력을 기반으로, 당신에게 어울리는 국내 여행지 3곳을 추천해드려요! 🧳✨")

# =========================================================
# Survey
# =========================================================
st.subheader("📝 선호도 조사")

q1 = st.radio(
    "질문 1: 여행 목적은 무엇인가요?",
    ["힐링", "휴양", "액티비티", "관광"],
    index=None,
    key="q1",
)

q2 = st.radio(
    "질문 2: 여행의 동반자는 누구인가요?",
    ["혼자", "연인", "가족", "친구"],
    index=None,
    key="q2",
)

q3 = st.radio(
    "질문 3: 이동수단은 어떻게 되나요?",
    ["고속버스", "기차", "자동차", "비행기"],
    index=None,
    key="q3",
)

st.divider()

# =========================================================
# Chat State
# =========================================================
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "좋아요! 😊\n예산, 여행 기간(몇박 몇일), 출발 지역, 좋아하는 분위기(바다/산/도시/맛집/카페 등)를 편하게 입력해줘요!"
        }
    ]

# =========================================================
# Chat UI
# =========================================================
st.subheader("💬 추가 정보 입력 (예산/기간/출발지 등)")
st.caption("이 대화 내용도 추천에 반영돼요.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# =========================================================
# OpenAI Streaming Helper
# =========================================================
def stream_openai(client: OpenAI, messages: list) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        stream=True,
    )

    full_text = ""
    placeholder = st.empty()

    for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full_text += delta
            placeholder.markdown(full_text)
            time.sleep(0.01)

    return full_text


# =========================================================
# TourAPI Request Helper
# =========================================================
def tourapi_get(endpoint: str, params: dict) -> dict:
    url = f"{TOUR_BASE}/{endpoint}"
    base_params = {
        "serviceKey": TOUR_API_KEY,
        "MobileOS": "ETC",
        "MobileApp": "MyTravelApp",
        "_type": "json",
    }
    base_params.update(params)

    r = requests.get(url, params=base_params, timeout=20)
    r.raise_for_status()
    return r.json()


def safe_items(data: dict) -> list:
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            return [items]
        return items
    except Exception:
        return []


# =========================================================
# Travel Spot Fetch
# =========================================================
def fetch_spots_by_area(area_code: int, limit: int = 20) -> list:
    """
    areaBasedList2로 관광지(12) 가져오기
    """
    data = tourapi_get(
        "areaBasedList2",
        {
            "areaCode": area_code,
            "contentTypeId": CONTENT_TYPE_TOUR,
            "numOfRows": limit,
            "pageNo": 1,
            "arrange": "P",  # 인기순
        },
    )
    return safe_items(data)


def filter_spots_with_images(spots: list) -> list:
    """
    이미지가 있는 것만 우선 사용
    """
    filtered = []
    for s in spots:
        img = s.get("firstimage") or s.get("firstimage2")
        if img:
            filtered.append(s)
    return filtered


# =========================================================
# OpenAI -> 추천 조건 추출(JSON)
# =========================================================
def extract_recommendation_plan(client: OpenAI, survey_context: str, chat_messages: list) -> dict:
    """
    OpenAI에게:
    - 지역 후보(areaCode) 2~3개
    - 여행 키워드
    - 추천 이유(한줄)
    를 JSON으로 뽑게 함
    """

    system_prompt = """
너는 국내 여행지 추천을 위한 플래너야.
사용자의 설문 결과 + 채팅 내용을 바탕으로
한국관광공사 TourAPI로 검색하기 적합한 추천 조건을 JSON으로만 출력해.

반드시 아래 형식만 출력할 것(설명 금지):

{
  "areas": [
    {"name": "서울", "areaCode": 1},
    {"name": "부산", "areaCode": 6},
    {"name": "제주", "areaCode": 39}
  ],
  "keywords": ["바다", "산책", "감성카페"],
  "style_summary": "짧은 힐링 여행 선호"
}

areaCode는 TourAPI 기준으로 추정해도 됨.
"""

    messages_for_api = [{"role": "system", "content": system_prompt}]
    messages_for_api.append({"role": "system", "content": survey_context})
    messages_for_api.extend(chat_messages)

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages_for_api,
        temperature=0.4,
    )

    text = res.choices[0].message.content.strip()

    # JSON 파싱
    try:
        return json.loads(text)
    except Exception:
        # JSON이 깨진 경우를 대비한 최소 폴백
        return {
            "areas": [{"name": "서울", "areaCode": 1}, {"name": "부산", "areaCode": 6}, {"name": "제주", "areaCode": 39}],
            "keywords": [],
            "style_summary": "일반적인 국내 여행 추천",
        }


# =========================================================
# 추천 여행지 선정 로직
# =========================================================
def pick_top3_spots(plan: dict) -> list:
    """
    - areas 순서대로 TourAPI에서 관광지 가져오기
    - 이미지 있는 것 우선
    - 중복 제거 후 3개 선택
    """
    picked = []
    seen = set()

    areas = plan.get("areas", [])
    if not areas:
        areas = [{"name": "서울", "areaCode": 1}, {"name": "부산", "areaCode": 6}, {"name": "제주", "areaCode": 39}]

    for area in areas:
        area_code = area.get("areaCode")
        if not area_code:
            continue

        spots = fetch_spots_by_area(area_code, limit=30)
        spots = filter_spots_with_images(spots)

        for s in spots:
            cid = s.get("contentid")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            picked.append(s)
            if len(picked) >= 3:
                return picked

    return picked[:3]


# =========================================================
# Card UI
# =========================================================
def render_spot_card(spot: dict, why: str):
    title = spot.get("title", "이름 없음")
    addr = spot.get("addr1", "")
    img = spot.get("firstimage") or spot.get("firstimage2")
    overview = spot.get("overview", "")

    with st.container(border=True):
        if img:
            st.image(img, use_container_width=True)
        else:
            st.write("🖼️ 이미지 없음")

        st.markdown(f"### 📍 {title}")
        if addr:
            st.caption(f"📌 {addr}")

        st.write(why)


# =========================================================
# Chat Input
# =========================================================
user_input = st.chat_input("예: 예산 20만원, 1박2일, 서울 출발, 바다+맛집 위주!")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.write(user_input)

    if not OPENAI_API_KEY:
        with st.chat_message("assistant"):
            st.error("OpenAI API Key가 없어요! 사이드바에 입력해 주세요.")
        st.stop()

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 챗봇은 아직 결과 추천이 아니라 정보 수집용
    system_prompt_chat = """
너는 국내 여행지 추천을 위한 정보 수집용 챗봇이야.
사용자의 예산, 여행 기간, 출발지, 선호 활동(맛집/바다/산/도시/카페 등)을 자연스럽게 파악하고,
추가로 필요한 정보가 있으면 질문해.

중요:
- 지금은 여행지를 추천하지 말 것.
- 정보 수집과 질문만 할 것.
- 말투는 친근하고 간단하게.
"""

    survey_context = f"""
[현재 사용자의 선택]
- 여행 목적: {q1}
- 동반자: {q2}
- 이동수단: {q3}
"""

    messages_for_api = [{"role": "system", "content": system_prompt_chat}]
    messages_for_api.append({"role": "system", "content": survey_context})
    messages_for_api.extend(st.session_state.messages)

    with st.chat_message("assistant"):
        try:
            assistant_text = stream_openai(client, messages_for_api)
        except Exception as e:
            st.error("OpenAI 요청 중 오류가 발생했어요.")
            st.caption(str(e))
            st.stop()

    st.session_state.messages.append({"role": "assistant", "content": assistant_text})


# =========================================================
# Result Button
# =========================================================
st.divider()

if st.button("결과 보기", type="primary"):
    if not OPENAI_API_KEY:
        st.error("OpenAI API Key를 사이드바에 입력해주세요.")
        st.stop()

    if not TOUR_API_KEY:
        st.error("TourAPI ServiceKey를 사이드바에 입력해주세요.")
        st.stop()

    if q1 is None or q2 is None or q3 is None:
        st.warning("모든 질문에 답해야 결과를 볼 수 있어요!")
        st.stop()

    client = OpenAI(api_key=OPENAI_API_KEY)

    survey_context = f"""
[사용자 선호도 조사 결과]
- 여행 목적: {q1}
- 동반자: {q2}
- 이동수단: {q3}
"""

    with st.spinner("당신에게 어울리는 여행지를 찾는 중... 🧳✨"):
        # 1) OpenAI로 추천 계획(JSON) 추출
        plan = extract_recommendation_plan(client, survey_context, st.session_state.messages)

        # 2) TourAPI로 여행지 후보 검색 후 3개 선정
        spots = pick_top3_spots(plan)

    # 결과 출력
    st.markdown("## ✅ 추천 국내 여행지 3곳")

    style_summary = plan.get("style_summary", "")
    keywords = plan.get("keywords", [])

    if style_summary:
        st.caption(f"여행 스타일: {style_summary}")
    if keywords:
        st.caption("추천 키워드: " + ", ".join(keywords))

    if not spots:
        st.warning("추천 여행지를 찾지 못했어요. 지역을 바꿔서 다시 시도해 주세요!")
        st.stop()

    # 카드 3개를 가로로
    cols = st.columns(3)

    for i, spot in enumerate(spots):
        why = "선호도(목적/동반자/이동수단) + 채팅으로 입력한 조건에 잘 맞는 여행지예요!"
        with cols[i]:
            render_spot_card(spot, why)
