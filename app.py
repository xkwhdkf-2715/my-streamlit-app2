import os
import json
import time
import random
import urllib.parse
import re
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
st.caption("추천 품질을 위해 최소 '이동수단/여행기간/선호풍경'은 1개 이상 선택하는 것을 추천해요.")

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
    # ✅ 풍경/교통을 최우선으로 만들기 위해 풍경도 필수로
    return bool(transport) and bool(trip_days) and bool(scenery)

def build_chat_summary(messages: list) -> str:
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    return " / ".join(user_msgs[-3:]) if user_msgs else "추가 입력 없음"

# =========================================================
# ✅ OpenAI safe call
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

def fetch_spots_by_area(area_code: int, limit: int = 120) -> list:
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
    return [s for s in spots if (s.get("firstimage") or s.get("firstimage2"))]

# =========================================================
# ✅ 교통 제약(섬 제거) + 풍경 랭킹
# =========================================================
ISLAND_KEYWORDS = [
    "울릉", "독도", "백령", "연평", "가파", "마라도", "추자", "흑산", "홍도", "비양", "청산도", "거문도",
    "울릉군", "옹진군"
]

SEA_HINTS = ["해변", "바다", "해수욕장", "항", "포구", "등대", "섬", "해안", "갯벌", "선착장", "바닷길", "해안도로"]
MOUNTAIN_HINTS = ["산", "등산", "트레킹", "케이블카", "계곡", "정상", "국립공원", "숲", "오름"]
CITY_HINTS = ["도심", "시내", "거리", "광장", "전망대", "타워", "야경", "시장", "쇼핑", "문화", "전시", "뮤지엄"]

def filter_by_transport_constraints(spots: list, transport_list: list) -> list:
    t = set(transport_list)
    # 기차/버스 위주인데 비행기 미선택이면 "배 필수 섬" 제거
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
    return spots

def scenery_score(spot: dict, scenery_list: list) -> int:
    """
    ✅ 풍경을 최우선으로 반영하기 위한 점수.
    TourAPI 리스트에는 상세설명이 없을 수 있어 'title/addr' 기반 휴리스틱 + keyword를 섞어 점수화.
    """
    title = (spot.get("title") or "")
    addr = (spot.get("addr1") or "")
    text = f"{title} {addr}"

    score = 0
    chosen = set(scenery_list)

    # 바다 선호면 바다 관련 힌트 매칭 점수 크게
    if "바다" in chosen:
        score += sum(1 for h in SEA_HINTS if h in text) * 4

    if "산" in chosen:
        score += sum(1 for h in MOUNTAIN_HINTS if h in text) * 4

    if "도시" in chosen:
        score += sum(1 for h in CITY_HINTS if h in text) * 3

    # 주소 기반 보정(해안권/산간권 느낌)
    if "바다" in chosen and any(k in addr for k in ["해변", "항", "포구", "해수욕장", "해안"]):
        score += 6
    if "산" in chosen and any(k in addr for k in ["산", "계곡", "국립공원", "숲"]):
        score += 6

    return score

def prioritize_by_scenery(spots: list, scenery_list: list, top_k: int = 60) -> list:
    """
    ✅ 풍경 점수로 정렬 후 상위 top_k만 남김 (이후 랜덤/다양성 적용)
    """
    scored = [(scenery_score(s, scenery_list), s) for s in spots]
    scored.sort(key=lambda x: x[0], reverse=True)
    # 점수 0인 게 너무 많으면 잘못된 추천이 될 수 있으니, 최소 필터링을 줌
    nonzero = [s for sc, s in scored if sc > 0]
    if len(nonzero) >= 10:
        return nonzero[:top_k]
    # 점수가 거의 안 잡힐 경우(주소/제목만으로는 한계) 상위 일부만
    return [s for _, s in scored[:top_k]]

# =========================================================
# OpenAI -> Plan (풍경/교통 최우선 강제)
# =========================================================
def extract_recommendation_plan(client: OpenAI, survey_context: str, chat_messages: list) -> dict:
    transport_rules = f"""
- 교통수단 제약은 최우선이다.
- 사용자가 선택하지 않은 교통수단(비행기/배/렌터카)을 전제로 추천하면 안 된다.
- 특히 '기차/고속버스' 중심이면 울릉도/백령도 등 선박 필수 섬은 추천 금지.
"""
    scenery_rules = f"""
- 선호 풍경/환경은 추천의 1순위 조건이다.
- 사용자가 '바다'를 선택했으면 바다/해변/해안 위주로 추천하고, 산 위주 장소는 피하라.
- '산'을 선택했으면 산/계곡/숲/트레킹 위주로 추천하고, 해변 위주 장소는 피하라.
- '도시'를 선택했으면 도심/문화/전시/거리 위주로 추천하라.
"""

    system_prompt = f"""
너는 국내 여행지 추천을 위한 플래너야.
사용자의 설문 결과 + 채팅 내용을 바탕으로 TourAPI 검색에 적합한 추천 조건을 JSON으로만 출력해.

반드시 지켜야 할 우선순위:
1) 선호 풍경/환경
2) 이동수단(교통 제약)
3) 여행 기간
4) 나머지 선호(활동/혼잡도/동반자/목적)

{scenery_rules}
{transport_rules}

형식(설명/코드블록 금지):
{{
  "areas": [
    {{"name": "서울", "areaCode": 1}},
    {{"name": "부산", "areaCode": 6}},
    {{"name": "강원", "areaCode": 32}}
  ],
  "keywords": ["바다", "해변", "카페"],
  "style_summary": "짧은 바다 힐링 여행"
}}

규칙:
- areas는 3~5개
- keywords는 5~8개로 풍경 중심(바다/산/도시)을 반드시 포함
- 위 우선순위를 어기면 안 된다.
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
            "areas": [{"name": "부산", "areaCode": 6}, {"name": "강원", "areaCode": 32}, {"name": "경남", "areaCode": 36}],
            "keywords": scenery[:] if scenery else [],
            "style_summary": "선호 풍경 중심 추천",
        }

# =========================================================
# Pick spots: 교통 필터 -> 풍경 랭킹 -> 랜덤 샘플
# =========================================================
def pick_3_spots_prioritized(plan: dict, seed: int) -> list:
    rng = random.Random(seed)
    areas = plan.get("areas", []) or [{"name": "부산", "areaCode": 6}, {"name": "강원", "areaCode": 32}, {"name": "경남", "areaCode": 36}]

    pool, seen = [], set()

    for area in areas[:5]:
        code = area.get("areaCode")
        if not code:
            continue

        spots = filter_spots_with_images(fetch_spots_by_area(code, limit=120))
        spots = filter_by_transport_constraints(spots, transport)         # ✅ 교통 필터 먼저
        spots = prioritize_by_scenery(spots, scenery, top_k=70)           # ✅ 풍경 랭킹 최우선

        for s in spots:
            cid = s.get("contentid")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            pool.append(s)

    # 풍경 점수 0이 너무 많아서 풀 자체가 빈약하면 area만 바꿔서라도 확보
    if len(pool) < 10:
        # fallback: 풍경 랭킹만 완화(그래도 교통 필터는 유지)
        pool2, seen2 = [], set()
        for area in areas[:5]:
            code = area.get("areaCode")
            if not code:
                continue
            spots = filter_spots_with_images(fetch_spots_by_area(code, limit=120))
            spots = filter_by_transport_constraints(spots, transport)
            for s in spots:
                cid = s.get("contentid")
                if not cid or cid in seen2:
                    continue
                seen2.add(cid)
                pool2.append(s)
        pool = pool2

    if len(pool) <= 3:
        return pool[:3]

    # ✅ 상위 후보에서 랜덤(다시 뽑기 시 결과 변화 유지)
    top_pool = pool[:60] if len(pool) > 60 else pool
    return rng.sample(top_pool, 3)

# =========================================================
# OpenAI -> Reason (풍경/교통 어기지 말라고 추가)
# =========================================================
def generate_reason_for_spot(openai_key: str, survey_brief: str, chat_summary: str, spot_title: str, spot_addr: str) -> str:
    client = OpenAI(api_key=openai_key)
    prompt = f"""
너는 국내 여행지 추천 전문가야.
아래 관광지를 추천하는 이유를 1~2문장으로 아주 깔끔하게 작성해줘.

반드시 지켜:
- 사용자가 선택한 선호 풍경(바다/산/도시)과 이동수단을 최우선으로 반영
- 사용자가 선택하지 않은 교통수단(비행기/배/렌터카)을 전제로 말하지 말 것
- 관광지 이름 포함, 최대 2문장, 과장 금지

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
    if scenery:
        st.markdown(f"<span class='tag'>🌄 풍경: {', '.join(scenery)}</span>", unsafe_allow_html=True)
    if transport:
        st.markdown(f"<span class='tag'>🚆 이동수단: {', '.join(transport)}</span>", unsafe_allow_html=True)
    if trip_days:
        st.markdown(f"<span class='tag'>🗓️ 기간: {', '.join(trip_days)}</span>", unsafe_allow_html=True)
    if purpose:
        st.markdown(f"<span class='tag'>🎯 목적: {', '.join(purpose)}</span>", unsafe_allow_html=True)
    if companion:
        st.markdown(f"<span class='tag'>👥 동반자: {', '.join(companion)}</span>", unsafe_allow_html=True)
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
사용자의 예산/출발지/제약을 파악하고 부족한 정보가 있으면 질문해.
중요: 지금은 장소 추천하지 말고 정보 수집만 해.
"""

    survey_context_chat = f"""
[현재 사용자의 선택]
- 선호 풍경: {join_or_none(scenery)}
- 이동수단: {join_or_none(transport)}
- 기간: {join_or_none(trip_days)}
- 목적: {join_or_none(purpose)}
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
- 선호 풍경/환경: {join_or_none(scenery)}
- 이동수단: {join_or_none(transport)}
- 기간: {join_or_none(trip_days)}
- 목적: {join_or_none(purpose)}
- 동반자: {join_or_none(companion)}
- 활동: {join_or_none(activities)}
- 혼잡도: {join_or_none(crowd)}
"""

    plan = extract_recommendation_plan(client, survey_context, st.session_state.messages)
    spots = pick_3_spots_prioritized(plan, seed=st.session_state.rerun_seed)

    chat_summary = build_chat_summary(st.session_state.messages)
    survey_brief = (
        f"풍경={join_or_none(scenery)} / 교통={join_or_none(transport)} / 기간={join_or_none(trip_days)} / "
        f"목적={join_or_none(purpose)} / 활동={join_or_none(activities)} / 혼잡도={join_or_none(crowd)}"
    )

    reasons = {}
    for spot in spots:
        cid = spot.get("contentid", "")
        title = spot.get("title", "")
        addr = spot.get("addr1", "")
        reasons[cid] = generate_reason_for_spot(OPENAI_API_KEY, survey_brief, chat_summary, title, addr)

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
        st.warning("추천을 위해 최소한 '선호풍경/이동수단/여행기간'은 1개 이상 선택해주세요!")
        st.stop()

    with st.spinner("선호 풍경/교통을 최우선으로 장소를 찾는 중... 🌊🚆"):
        generate_recommendations()

if reroll:
    if st.session_state.results is None:
        st.warning("먼저 '결과 보기'를 눌러 추천을 생성해 주세요!")
    else:
        if not OPENAI_API_KEY or not TOUR_API_KEY:
            st.error("사이드바에 OpenAI 키와 TourAPI 키를 입력해주세요.")
            st.stop()
        st.session_state.rerun_seed += 1
        with st.spinner("선호 풍경/교통을 최우선으로 새 추천을 만드는 중... 🔄"):
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
