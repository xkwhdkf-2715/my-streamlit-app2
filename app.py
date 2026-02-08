import os
import json
import time
import random
import urllib.parse
import requests
import streamlit as st
from openai import OpenAI
from openai import APIConnectionError, RateLimitError, APITimeoutError, APIError

# =========================================================
# Page
# =========================================================
st.set_page_config(
    page_title="내가 선호하는 국내 여행지는?",
    page_icon="🧳",
    layout="wide",
)

# =========================================================
# Sidebar: API Keys
# =========================================================
st.sidebar.header("🔑 API 설정")
openai_key_input = st.sidebar.text_input("OpenAI API Key", type="password")
tour_key_input = st.sidebar.text_input("TourAPI ServiceKey", type="password")
st.sidebar.caption("OpenAI 키 + 한국관광공사 TourAPI 키를 입력해야 추천이 작동해요.")

OPENAI_API_KEY = openai_key_input or os.getenv("OPENAI_API_KEY", "")
TOUR_API_KEY = tour_key_input or os.getenv("TOUR_API_KEY", "")

# =========================================================
# TourAPI Constants
# =========================================================
TOUR_BASE = "https://apis.data.go.kr/B551011/KorService2"
CONTENT_TYPE_TOUR = 12  # 관광지

# =========================================================
# CSS
# =========================================================
st.markdown(
    """
    <style>
    .spot-title { font-size: 22px; font-weight: 800; margin-top: 10px; margin-bottom: 6px; }
    .spot-addr { font-size: 14px; opacity: 0.7; margin-bottom: 10px; }
    .spot-reason {
        font-size: 15px; line-height: 1.5;
        background: rgba(0,0,0,0.04);
        padding: 12px 12px; border-radius: 14px;
        margin-top: 10px; margin-bottom: 10px;
    }
    .tagbox { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; margin-bottom: 10px; }
    .tag { font-size: 13px; padding: 6px 10px; border-radius: 999px; background: rgba(0,0,0,0.06); }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# Session State
# =========================================================
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "좋아요! 😊\n예산, 출발지(예: 서울/부산), 날짜(몇박 몇일), 하고 싶은 것(맛집/카페/전시/온천 등)을 편하게 입력해줘요!"}]

if "results" not in st.session_state:
    st.session_state.results = None
if "plan" not in st.session_state:
    st.session_state.plan = None
if "reasons" not in st.session_state:
    st.session_state.reasons = {}
if "rerun_seed" not in st.session_state:
    st.session_state.rerun_seed = 0

# =========================================================
# UI Header
# =========================================================
st.title("내가 선호하는 국내 여행지는?")
st.caption("선호도 조사(복수 선택) + 추가 입력을 기반으로, 당신에게 어울리는 국내 여행지 3곳을 추천해드려요! 🧳✨")

# =========================================================
# Survey
# =========================================================
st.subheader("📝 선호도 조사 (복수 선택 가능)")
st.caption("각 질문에서 여러 개 선택해도 괜찮아요! (추천 품질을 위해 최소 핵심 항목은 1개 이상 선택해주세요)")

purpose = st.multiselect("질문 1: 여행 목적은 무엇인가요?", ["힐링", "휴양", "액티비티", "관광"], default=[], key="purpose")
companion = st.multiselect("질문 2: 여행의 동반자는 누구인가요?", ["혼자", "연인", "가족", "친구"], default=[], key="companion")
transport = st.multiselect("질문 3: 이동수단은 어떻게 되나요?", ["고속버스", "기차", "자동차", "비행기"], default=[], key="transport")
trip_days = st.multiselect("질문 4: 여행 기간은 어떻게 되나요?", ["당일여행", "1박 2일", "2박 3일", "3박 이상"], default=[], key="trip_days")
scenery = st.multiselect("질문 5: 선호 풍경/환경은 무엇인가요?", ["바다", "산", "도시"], default=[], key="scenery")
activities = st.multiselect("질문 6: 하고 싶은 활동은 무엇인가요?", ["맛집 탐방", "카페 투어", "사진 스팟", "온천,스파", "역사,문화", "전시, 뮤지엄", "테마파크"], default=[], key="activities")
crowd = st.multiselect("질문 7: 혼잡도 선호는 어떤가요?", ["사람 많은 핫플", "조용하고 한적한 곳"], default=[], key="crowd")

st.divider()

# =========================================================
# Helpers
# =========================================================
def join_or_none(values: list) -> str:
    return ", ".join(values) if values else "선택 없음"

def validate_min_one_each() -> bool:
    return bool(purpose) and bool(transport) and bool(trip_days)

def build_chat_summary(messages: list) -> str:
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    return " / ".join(user_msgs[-3:]) if user_msgs else "추가 입력 없음"

# ✅ 교통 제약 규칙 텍스트 (OpenAI 프롬프트에 강제)
def transport_rules_text(transport_list: list) -> str:
    t = set(transport_list)

    rules = []
    rules.append("교통수단 제약은 최우선이다. 사용자가 선택하지 않은 교통수단을 전제로 추천하면 안 된다.")

    # 섬/선박 이슈: 버스/기차-only라면 섬은 금지
    if ("고속버스" in t or "기차" in t) and ("비행기" not in t):
        rules.append("비행기를 선택하지 않았다면, 항공 의존 지역(특히 제주)은 우선순위를 낮추고, '울릉도/독도/백령도/연평도/가파도/마라도/추자도/흑산도/홍도' 등 선박이 사실상 필수인 섬 지역은 추천하지 마라.")

    if ("고속버스" in t or "기차" in t) and ("자동차" not in t):
        rules.append("자동차를 선택하지 않았다면, 렌터카/자가용이 거의 필수인 외곽·섬·산간 지역은 피하고, 대중교통만으로 이동하기 쉬운 도시권/역·터미널 중심 권역을 우선 추천하라.")

    # 비행기 only면: 공항권 우선
    if "비행기" in t and len(t) == 1:
        rules.append("비행기만 선택했다면 공항 접근성이 좋은 권역을 우선하라(예: 제주, 부산, 김해/김포/제주공항 등).")

    # 자동차 only면: 드라이브/자차 접근 좋은 곳
    if "자동차" in t and len(t) == 1:
        rules.append("자동차만 선택했다면 드라이브/자차 접근성이 좋은 권역을 우선하라(근교/해안도로/국립공원 등).")

    # 기차-only면: KTX/기차 접근 가능한 도시 중심
    if "기차" in t and len(t) == 1:
        rules.append("기차만 선택했다면 KTX/기차역 접근이 좋은 도시/권역을 우선하라(예: 강릉, 전주, 부산, 대전, 경주 등).")

    # 버스-only면: 터미널 접근 가능한 도시 중심
    if "고속버스" in t and len(t) == 1:
        rules.append("고속버스만 선택했다면 고속버스터미널로 접근하기 쉬운 도시/권역을 우선하라(예: 전주, 속초, 대구 등).")

    return "\n- " + "\n- ".join(rules)

# =========================================================
# ✅ OpenAI safe call (retry + stream fallback)
# =========================================================
def safe_openai_chat_create(client: OpenAI, **kwargs):
    max_retries = 3
    base_sleep = 1.2
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except (APIConnectionError, APITimeoutError, RateLimitError, APIError) as e:
            last_err = e
            time.sleep(base_sleep * (2 ** attempt))
    raise last_err

def stream_openai_safe(client: OpenAI, messages: list) -> str:
    placeholder = st.empty()
    full_text = ""
    try:
        stream = safe_openai_chat_create(client, model="gpt-4o-mini", messages=messages, stream=True)
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text += delta
                placeholder.markdown(full_text)
                time.sleep(0.01)
        return full_text
    except (APIConnectionError, APITimeoutError, RateLimitError, APIError):
        placeholder.info("연결이 불안정해서 스트리밍 대신 일반 응답으로 전환했어요.")
        res = safe_openai_chat_create(client, model="gpt-4o-mini", messages=messages, stream=False)
        text = res.choices[0].message.content.strip()
        placeholder.markdown(text)
        return text

# =========================================================
# TourAPI
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

def fetch_spots_by_area(area_code: int, limit: int = 80) -> list:
    data = tourapi_get(
        "areaBasedList2",
        {
            "areaCode": area_code,
            "contentTypeId": CONTENT_TYPE_TOUR,
            "numOfRows": limit,
            "pageNo": 1,
            "arrange": "P",
        },
    )
    return safe_items(data)

def filter_spots_with_images(spots: list) -> list:
    return [s for s in spots if (s.get("firstimage") or s.get("firstimage2"))]

# ✅ 교통 제약 기반 “이상한 곳” 2차 필터
ISLAND_KEYWORDS = [
    "울릉", "독도", "백령", "연평", "가파", "마라도", "추자", "흑산", "홍도", "비양", "청산도", "거문도",
    "울릉군", "옹진군"  # 행정구역 힌트
]

def filter_by_transport_constraints(spots: list, transport_list: list) -> list:
    t = set(transport_list)

    # 기차/버스 위주이고 비행기/자동차가 없는 경우: 섬/선박 의존 키워드 제거
    if (("기차" in t) or ("고속버스" in t)) and ("비행기" not in t):
        filtered = []
        for s in spots:
            title = (s.get("title") or "")
            addr = (s.get("addr1") or "")
            text = f"{title} {addr}"
            if any(k in text for k in ISLAND_KEYWORDS):
                continue
            filtered.append(s)
        return filtered

    # 그 외에는 그대로
    return spots

# =========================================================
# OpenAI -> Plan (교통 제약 강제)
# =========================================================
def extract_recommendation_plan(client: OpenAI, survey_context: str, chat_messages: list) -> dict:
    rules = transport_rules_text(transport)

    system_prompt = f"""
너는 국내 여행지 추천을 위한 플래너야.
사용자의 설문 결과 + 채팅 내용을 바탕으로
한국관광공사 TourAPI로 검색하기 적합한 추천 조건을 JSON으로만 출력해.

⚠️ 반드시 "교통수단 제약"을 최우선으로 지켜라.
{rules}

반드시 아래 형식만 출력(설명/코드블록 금지):

{{
  "areas": [
    {{"name": "서울", "areaCode": 1}},
    {{"name": "부산", "areaCode": 6}},
    {{"name": "제주", "areaCode": 39}}
  ],
  "keywords": ["바다", "산책", "감성카페"],
  "style_summary": "짧은 힐링 여행 선호"
}}

규칙:
- areas는 3~5개 추천
- keywords는 3~6개
- style_summary는 1줄
- 교통 제약을 어기는 지역은 areas에 포함하지 마라.
"""

    messages_for_api = [{"role": "system", "content": system_prompt}]
    messages_for_api.append({"role": "system", "content": survey_context})
    messages_for_api.extend(chat_messages)

    res = safe_openai_chat_create(client, model="gpt-4o-mini", messages=messages_for_api, temperature=0.2)
    text = res.choices[0].message.content.strip()

    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        return json.loads(text)
    except Exception:
        return {
            "areas": [{"name": "서울", "areaCode": 1}, {"name": "부산", "areaCode": 6}, {"name": "강원", "areaCode": 32}],
            "keywords": [],
            "style_summary": "일반적인 국내 여행 추천",
        }

# =========================================================
# Pick spots (with transport filter)
# =========================================================
def pick_3_random_spots(plan: dict, seed: int) -> list:
    rng = random.Random(seed)
    areas = plan.get("areas", []) or [{"name": "서울", "areaCode": 1}, {"name": "부산", "areaCode": 6}, {"name": "강원", "areaCode": 32}]

    pool, seen = [], set()
    for area in areas[:5]:
        code = area.get("areaCode")
        if not code:
            continue

        spots = filter_spots_with_images(fetch_spots_by_area(code, limit=80))
        spots = filter_by_transport_constraints(spots, transport)  # ✅ 여기서 2차 필터

        for s in spots:
            cid = s.get("contentid")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            pool.append(s)

    # pool이 너무 작아지면 (필터가 너무 강할 때) 필터 완화 fallback
    if len(pool) < 3:
        pool2 = []
        seen2 = set()
        for area in areas[:5]:
            code = area.get("areaCode")
            if not code:
                continue
            spots = filter_spots_with_images(fetch_spots_by_area(code, limit=80))
            for s in spots:
                cid = s.get("contentid")
                if not cid or cid in seen2:
                    continue
                seen2.add(cid)
                pool2.append(s)
        pool = pool2

    if len(pool) <= 3:
        return pool[:3]
    return rng.sample(pool, 3)

# =========================================================
# OpenAI -> Reason
# =========================================================
def generate_reason_for_spot(openai_key: str, survey_brief: str, chat_summary: str, spot_title: str, spot_addr: str, keywords: list) -> str:
    client = OpenAI(api_key=openai_key)
    prompt = f"""
너는 국내 여행지 추천 전문가야.
아래 관광지를 추천하는 이유를 1~2문장으로 아주 깔끔하게 작성해줘.

조건:
- 문장은 최대 2문장
- 과장 금지
- 관광지 이름 포함
- 사용자의 선호(목적/기간/교통/활동/혼잡도/풍경) 중 최소 2개 반영
- 교통 제약을 어기는 내용(예: 비행기/배 필요 등)은 절대 말하지 마라.

[사용자 선호(요약)]
{survey_brief}

[추가 입력 요약]
{chat_summary}

[관광지]
- 이름: {spot_title}
- 주소: {spot_addr}
"""
    res = safe_openai_chat_create(
        client,
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "너는 짧고 깔끔하게 말하는 여행 추천 AI야."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return res.choices[0].message.content.strip()

# =========================================================
# Map links (vertical)
# =========================================================
def render_map_links_vertical(title: str, lat, lng):
    q = urllib.parse.quote(title)
    kakao = f"https://map.kakao.com/link/search/{q}"
    naver = f"https://map.naver.com/v5/search/{q}"
    google = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}" if lat and lng else f"https://www.google.com/maps/search/?api=1&query={q}"

    st.link_button("카카오맵", kakao, use_container_width=True)
    st.link_button("네이버지도", naver, use_container_width=True)
    st.link_button("구글지도", google, use_container_width=True)

# =========================================================
# Card UI
# =========================================================
def render_spot_card(spot: dict, reason: str):
    title = spot.get("title", "이름 없음")
    addr = spot.get("addr1", "")
    img = spot.get("firstimage") or spot.get("firstimage2")
    lat = spot.get("mapy")
    lng = spot.get("mapx")

    if img:
        st.image(img, use_container_width=True)
    else:
        st.write("🖼️ 이미지 없음")

    st.markdown(f'<div class="spot-title">📍 {title}</div>', unsafe_allow_html=True)
    if addr:
        st.markdown(f'<div class="spot-addr">{addr}</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="spot-reason">{reason}</div>', unsafe_allow_html=True)

    st.markdown("<div class='tagbox'>", unsafe_allow_html=True)
    if purpose:
        st.markdown(f"<span class='tag'>🎯 목적: {', '.join(purpose)}</span>", unsafe_allow_html=True)
    if trip_days:
        st.markdown(f"<span class='tag'>🗓️ 기간: {', '.join(trip_days)}</span>", unsafe_allow_html=True)
    if companion:
        st.markdown(f"<span class='tag'>👥 동반자: {', '.join(companion)}</span>", unsafe_allow_html=True)
    if transport:
        st.markdown(f"<span class='tag'>🚆 이동수단: {', '.join(transport)}</span>", unsafe_allow_html=True)
    if scenery:
        st.markdown(f"<span class='tag'>🌄 풍경: {', '.join(scenery)}</span>", unsafe_allow_html=True)
    if activities:
        shown = activities[:3]
        more = f" 외 {len(activities) - 3}개" if len(activities) > 3 else ""
        st.markdown(f"<span class='tag'>🎡 활동: {', '.join(shown)}{more}</span>", unsafe_allow_html=True)
    if crowd:
        st.markdown(f"<span class='tag'>👣 혼잡도: {', '.join(crowd)}</span>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    render_map_links_vertical(title, lat, lng)

# =========================================================
# Chat UI
# =========================================================
st.subheader("💬 추가 정보 입력 (예산/출발지/특이사항)")
st.caption("이 대화 내용도 추천에 반영돼요.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

user_input = st.chat_input("예: 예산 20만원, 서울 출발, 1박2일, 바다+맛집 위주!")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    if not OPENAI_API_KEY:
        with st.chat_message("assistant"):
            st.error("OpenAI API Key가 없어요! 사이드바에 입력해 주세요.")
        st.stop()

    client = OpenAI(api_key=OPENAI_API_KEY)
    system_prompt_chat = """
너는 국내 여행지 추천을 위한 정보 수집용 챗봇이야.
사용자의 예산, 출발지, 제약사항을 파악하고, 더 필요한 정보가 있으면 질문해.
중요: 지금은 여행지를 추천하지 말고 정보 수집만 해.
"""

    survey_context_chat = f"""
[현재 사용자의 선택]
- 목적: {join_or_none(purpose)}
- 동반자: {join_or_none(companion)}
- 이동수단: {join_or_none(transport)}
- 기간: {join_or_none(trip_days)}
- 풍경: {join_or_none(scenery)}
- 활동: {join_or_none(activities)}
- 혼잡도: {join_or_none(crowd)}
"""

    messages_for_api = [{"role": "system", "content": system_prompt_chat}]
    messages_for_api.append({"role": "system", "content": survey_context_chat})
    messages_for_api.extend(st.session_state.messages)

    with st.chat_message("assistant"):
        assistant_text = stream_openai_safe(client, messages_for_api)

    st.session_state.messages.append({"role": "assistant", "content": assistant_text})

# =========================================================
# Recommendation Pipeline
# =========================================================
def generate_recommendations():
    client = OpenAI(api_key=OPENAI_API_KEY)

    survey_context = f"""
[선호도 조사]
- 목적: {join_or_none(purpose)}
- 기간: {join_or_none(trip_days)}
- 동반자: {join_or_none(companion)}
- 이동수단: {join_or_none(transport)}
- 풍경: {join_or_none(scenery)}
- 활동: {join_or_none(activities)}
- 혼잡도: {join_or_none(crowd)}
"""

    plan = extract_recommendation_plan(client, survey_context, st.session_state.messages)

    spots = pick_3_random_spots(plan, seed=st.session_state.rerun_seed)

    chat_summary = build_chat_summary(st.session_state.messages)
    keywords = plan.get("keywords", [])

    survey_brief = (
        f"목적={join_or_none(purpose)} / 기간={join_or_none(trip_days)} / 동반자={join_or_none(companion)} / "
        f"교통={join_or_none(transport)} / 풍경={join_or_none(scenery)} / 활동={join_or_none(activities)} / 혼잡도={join_or_none(crowd)}"
    )

    reasons = {}
    for spot in spots:
        cid = spot.get("contentid", "")
        title = spot.get("title", "")
        addr = spot.get("addr1", "")
        reasons[cid] = generate_reason_for_spot(OPENAI_API_KEY, survey_brief, chat_summary, title, addr, keywords)

    st.session_state.plan = plan
    st.session_state.results = spots
    st.session_state.reasons = reasons

# =========================================================
# Buttons
# =========================================================
st.divider()
col_a, col_b = st.columns([1, 1])
with col_a:
    run_result = st.button("결과 보기", type="primary")
with col_b:
    reroll = st.button("🔄 결과 다시 뽑기", type="secondary", help="설문/대화는 그대로 두고 결과만 새로 추천해요.")

if run_result:
    if not OPENAI_API_KEY:
        st.error("OpenAI API Key를 사이드바에 입력해주세요.")
        st.stop()
    if not TOUR_API_KEY:
        st.error("TourAPI ServiceKey를 사이드바에 입력해주세요.")
        st.stop()
    if not validate_min_one_each():
        st.warning("추천을 위해 최소한 '목적/이동수단/여행기간'은 1개 이상 선택해주세요!")
        st.stop()

    with st.spinner("당신에게 어울리는 장소를 찾는 중... 🧳✨"):
        generate_recommendations()

if reroll:
    if st.session_state.results is None:
        st.warning("먼저 '결과 보기'를 눌러 추천을 생성해 주세요!")
    else:
        if not OPENAI_API_KEY or not TOUR_API_KEY:
            st.error("사이드바에 OpenAI 키와 TourAPI 키를 입력해주세요.")
            st.stop()
        st.session_state.rerun_seed += 1
        with st.spinner("새로운 장소를 다시 추천하는 중... 🔄✨"):
            generate_recommendations()
        st.rerun()

# =========================================================
# Results
# =========================================================
if st.session_state.results:
    st.markdown("# 지금 당신에게 딱인 장소는 ...")
    cols = st.columns(3)
    for i, spot in enumerate(st.session_state.results):
        cid = spot.get("contentid", "")
        reason = st.session_state.reasons.get(cid, "선호도와 입력한 조건에 잘 맞는 장소예요!")
        with cols[i]:
            render_spot_card(spot, reason)
