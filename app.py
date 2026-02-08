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
    st.session_state.messages = [
        {"role": "assistant", "content": "좋아요! 😊\n예산, 출발지(예: 서울/부산), 날짜(몇박 몇일), 하고 싶은 것(맛집/카페/전시/온천 등)을 편하게 입력해줘요!"}
    ]
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
st.caption("정확한 추천을 위해 최소 '선호 풍경/이동수단/여행기간'은 1개 이상 선택해주세요.")

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
    return bool(scenery) and bool(transport) and bool(trip_days)

def build_chat_summary(messages: list) -> str:
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    return " / ".join(user_msgs[-3:]) if user_msgs else "추가 입력 없음"

# =========================================================
# OpenAI safe call
# =========================================================
def safe_openai_chat_create(client: OpenAI, **kwargs):
    max_retries = 3
    base_sleep = 1.3
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except (APIConnectionError, APITimeoutError, RateLimitError, APIError) as e:
            last_err = e
            time.sleep(base_sleep * (2 ** attempt))
    raise last_err

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

    r = requests.get(url, params=base_params, timeout=25)
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

def fetch_spots_by_area(area_code: int, limit: int = 180) -> list:
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

# =========================================================
# Priority Rules: 1) 풍경 2) 교통 3) 기타
# =========================================================
ISLAND_KEYWORDS = [
    "울릉", "독도", "백령", "연평", "가파", "마라도", "추자", "흑산", "홍도", "비양", "청산도", "거문도",
    "울릉군", "옹진군"
]

SEA_HINTS = ["해변", "바다", "해수욕장", "항", "포구", "등대", "해안", "갯벌", "선착장", "해안도로", "바닷길"]
MOUNTAIN_HINTS = ["산", "등산", "트레킹", "케이블카", "계곡", "정상", "국립공원", "숲", "오름", "둘레길"]
CITY_HINTS = ["도심", "시내", "거리", "광장", "전망대", "타워", "야경", "시장", "쇼핑", "문화", "전시", "뮤지엄", "박물관"]

def text_of(spot: dict) -> str:
    return f"{(spot.get('title') or '')} {(spot.get('addr1') or '')}"

def transport_filter(spots: list, transport_list: list) -> list:
    t = set(transport_list)
    if (("기차" in t) or ("고속버스" in t)) and ("비행기" not in t):
        out = []
        for s in spots:
            if any(k in text_of(s) for k in ISLAND_KEYWORDS):
                continue
            out.append(s)
        return out
    return spots

def scenery_match_score(spot: dict, scenery_list: list) -> int:
    txt = text_of(spot)
    chosen = set(scenery_list)
    score = 0
    if "바다" in chosen:
        score += sum(1 for h in SEA_HINTS if h in txt) * 10
    if "산" in chosen:
        score += sum(1 for h in MOUNTAIN_HINTS if h in txt) * 10
    if "도시" in chosen:
        score += sum(1 for h in CITY_HINTS if h in txt) * 8
    return score

def scenery_strict_filter(spots: list, scenery_list: list) -> list:
    if not scenery_list:
        return spots
    scored = [(scenery_match_score(s, scenery_list), s) for s in spots]
    scored.sort(key=lambda x: x[0], reverse=True)

    nonzero = [s for sc, s in scored if sc > 0]
    if len(nonzero) >= 20:
        return nonzero
    return [s for _, s in scored[:70]]

def other_preference_bonus(spot: dict) -> int:
    # 3순위(보조): 아주 약하게만
    txt = text_of(spot)
    bonus = 0
    if "사진 스팟" in activities and any(k in txt for k in ["전망", "포토", "타워", "전망대"]):
        bonus += 2
    if "역사,문화" in activities and any(k in txt for k in ["성", "궁", "박물관", "유적", "문화", "사찰"]):
        bonus += 2
    if "온천,스파" in activities and any(k in txt for k in ["온천", "스파", "탕"]):
        bonus += 2
    if "테마파크" in activities and any(k in txt for k in ["테마파크", "랜드", "월드"]):
        bonus += 2
    return bonus

def total_rank_score(spot: dict, scenery_list: list) -> int:
    # 풍경이 1순위 → 가중치 압도적으로
    scenic = scenery_match_score(spot, scenery_list) * 25
    bonus = other_preference_bonus(spot)  # 보조
    return scenic + bonus

# =========================================================
# Plan fallback (OpenAI 없어도 작동)
# =========================================================
def local_plan_fallback():
    # areaCode 참고: 1 서울, 2 인천, 3 대전, 4 대구, 5 광주, 6 부산, 7 울산, 8 세종,
    # 31 경기, 32 강원, 33 충북, 34 충남, 35 경북, 36 경남, 37 전북, 38 전남, 39 제주
    if "바다" in scenery:
        return {"areas": [{"name": "부산", "areaCode": 6}, {"name": "강원", "areaCode": 32}, {"name": "경남", "areaCode": 36}, {"name": "전남", "areaCode": 38}], "style_summary": "바다 선호"}
    if "산" in scenery:
        return {"areas": [{"name": "강원", "areaCode": 32}, {"name": "경북", "areaCode": 35}, {"name": "충북", "areaCode": 33}, {"name": "경기", "areaCode": 31}], "style_summary": "산 선호"}
    return {"areas": [{"name": "서울", "areaCode": 1}, {"name": "부산", "areaCode": 6}, {"name": "대구", "areaCode": 4}, {"name": "인천", "areaCode": 2}], "style_summary": "도시 선호"}

def extract_recommendation_plan(client: OpenAI, survey_context: str, chat_messages: list) -> dict:
    system_prompt = """
너는 국내 여행지 추천을 위한 플래너야.
JSON으로만 출력해.
areas는 4~6개 정도로 넓게 제안해.
"""
    messages_for_api = [{"role": "system", "content": system_prompt}]
    messages_for_api.append({"role": "system", "content": survey_context})
    messages_for_api.extend(chat_messages)

    res = safe_openai_chat_create(client, model="gpt-4o-mini", messages=messages_for_api, temperature=0.2)
    text = res.choices[0].message.content.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)

def pick_3_spots_strict_priority(plan: dict, seed: int) -> list:
    rng = random.Random(seed)
    areas = plan.get("areas", [])[:6]
    if not areas:
        areas = local_plan_fallback().get("areas", [])

    pool, seen = [], set()
    for area in areas:
        code = area.get("areaCode")
        if not code:
            continue
        spots = filter_spots_with_images(fetch_spots_by_area(code, limit=180))
        spots = transport_filter(spots, transport)        # 2순위
        spots = scenery_strict_filter(spots, scenery)     # 1순위(엄격)
        for s in spots:
            cid = s.get("contentid")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            pool.append(s)

    if not pool:
        return []

    ranked = sorted(pool, key=lambda s: total_rank_score(s, scenery), reverse=True)
    top = ranked[:80] if len(ranked) > 80 else ranked

    if len(top) <= 3:
        return top

    # 상위 30에서만 샘플링
    return rng.sample(top[:30], 3)

# =========================================================
# Reason fallback
# =========================================================
def local_reason_fallback(spot_title: str) -> str:
    s = ", ".join(scenery) if scenery else "선호 풍경"
    t = ", ".join(transport) if transport else "선호 이동수단"
    d = ", ".join(trip_days) if trip_days else "여행 기간"
    return f"{spot_title}은(는) '{s}' 분위기를 즐기기 좋고, '{t}' 기준으로 접근하기 쉬운 편이라 '{d}' 일정에 잘 맞아요."

def generate_reason_for_spot(openai_key: str, survey_brief: str, chat_summary: str, spot_title: str, spot_addr: str) -> str:
    client = OpenAI(api_key=openai_key)
    prompt = f"""
추천 이유를 1~2문장으로 아주 깔끔하게 작성해줘.

필수:
- 풍경(1순위) + 이동수단(2순위)을 반드시 반영
- 사용자가 선택하지 않은 교통수단(비행기/배/렌터카)을 전제로 말하지 말 것
- 관광지 이름 포함, 최대 2문장

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
    st.markdown(f"<span class='tag'>🌄 풍경(1순위): {', '.join(scenery)}</span>", unsafe_allow_html=True)
    st.markdown(f"<span class='tag'>🚆 이동수단(2순위): {', '.join(transport)}</span>", unsafe_allow_html=True)
    if trip_days:
        st.markdown(f"<span class='tag'>🗓️ 기간: {', '.join(trip_days)}</span>", unsafe_allow_html=True)
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

    # 여기서는 정보수집용이니까 OpenAI 없어도 에러 안내만
    if not OPENAI_API_KEY:
        with st.chat_message("assistant"):
            st.info("OpenAI 키를 넣으면 대화 기반 정보 수집을 더 잘 할 수 있어요! (지금은 설문 기반 추천만 가능)")
    else:
        # 간단 응답(스트리밍 없이도 OK) — 안정성을 위해 try/except
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            system_prompt_chat = """
너는 국내 여행지 추천을 위한 정보 수집용 챗봇이야.
예산/출발지/제약을 파악하고 부족한 정보가 있으면 질문해.
중요: 지금은 장소 추천하지 말고 정보 수집만 해.
"""
            survey_context_chat = f"""
[현재 사용자의 선택]
- 선호 풍경(1순위): {join_or_none(scenery)}
- 이동수단(2순위): {join_or_none(transport)}
- 기간: {join_or_none(trip_days)}
"""
            messages_for_api = [{"role": "system", "content": system_prompt_chat}]
            messages_for_api.append({"role": "system", "content": survey_context_chat})
            messages_for_api.extend(st.session_state.messages)

            res = safe_openai_chat_create(client, model="gpt-4o-mini", messages=messages_for_api, temperature=0.4)
            assistant_text = res.choices[0].message.content.strip()

            with st.chat_message("assistant"):
                st.write(assistant_text)

            st.session_state.messages.append({"role": "assistant", "content": assistant_text})

        except Exception:
            with st.chat_message("assistant"):
                st.info("지금은 네트워크가 불안정해서 대화 기능이 잠시 멈췄어요. 설문 기반 추천은 계속 사용할 수 있어요!")

# =========================================================
# Recommendation Pipeline (🔥 여기가 핵심: OpenAI 실패해도 앱 계속)
# =========================================================
def generate_recommendations():
    survey_context = f"""
[선호도 조사]
- 선호 풍경/환경(1순위): {join_or_none(scenery)}
- 이동수단(2순위): {join_or_none(transport)}
- 기간: {join_or_none(trip_days)}
- 목적: {join_or_none(purpose)}
- 활동: {join_or_none(activities)}
- 혼잡도: {join_or_none(crowd)}
"""

    # 1) plan: OpenAI 시도 → 실패하면 local fallback
    plan = None
    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            plan = extract_recommendation_plan(client, survey_context, st.session_state.messages)
        except Exception:
            plan = local_plan_fallback()
            st.info("OpenAI 연결이 불안정해서, 임시로 로컬 규칙 기반으로 추천을 만들었어요.")
    else:
        plan = local_plan_fallback()

    # 2) spot 선정: 풍경 1순위 + 교통 2순위로 엄격 랭킹
    spots = pick_3_spots_strict_priority(plan, seed=st.session_state.rerun_seed)

    # 3) reason: OpenAI 시도 → 실패하면 템플릿 fallback
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
        if OPENAI_API_KEY:
            try:
                reasons[cid] = generate_reason_for_spot(OPENAI_API_KEY, survey_brief, chat_summary, title, addr)
            except Exception:
                reasons[cid] = local_reason_fallback(title)
        else:
            reasons[cid] = local_reason_fallback(title)

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
    if not TOUR_API_KEY:
        st.error("TourAPI ServiceKey를 사이드바에 입력해주세요.")
        st.stop()
    if not validate_min_one_each():
        st.warning("추천을 위해 최소한 '선호풍경/이동수단/여행기간'은 1개 이상 선택해주세요!")
        st.stop()

    with st.spinner("풍경(1순위) → 이동수단(2순위) 기준으로 장소를 고르는 중... 🌊🚆"):
        generate_recommendations()

if reroll:
    if st.session_state.results is None:
        st.warning("먼저 '결과 보기'를 눌러 추천을 생성해 주세요!")
    else:
        st.session_state.rerun_seed += 1
        with st.spinner("풍경(1순위) → 이동수단(2순위) 기준으로 새 추천을 만드는 중... 🔄"):
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
