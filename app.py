import time
import requests
import streamlit as st
from collections import Counter
from typing import Dict, List, Tuple, Optional

# =============================
# Page
# =============================
st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="wide")

# =============================
# Constants
# =============================
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_DISCOVER_URL = f"{TMDB_API_BASE}/discover/movie"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

# 사용자 선택(4분류) -> TMDB with_genres 값 (OR는 |)
WITH_GENRES_MAP = {
    "로맨스/드라마": "10749|18",   # 로맨스 OR 드라마
    "액션/어드벤처": "28",
    "SF/판타지": "878|14",        # SF OR 판타지
    "코미디": "35",
}

# 결과 타이틀용
GENRE_TITLE = {
    "로맨스/드라마": "로맨스/드라마",
    "액션/어드벤처": "액션/어드벤처",
    "SF/판타지": "SF/판타지",
    "코미디": "코미디",
}

# 장르별 이모지 (카드에 표시)
GENRE_EMOJI = {
    "로맨스/드라마": "💘🎭",
    "액션/어드벤처": "🔥🧗",
    "SF/판타지": "🛸🧙‍♂️",
    "코미디": "🤣🎈",
}

# =============================
# Sidebar
# =============================
st.sidebar.header("🔑 TMDB 설정")
api_key = st.sidebar.text_input("TMDB API Key", type="password")
st.sidebar.caption("TMDB에서 발급받은 API Key를 입력하면 추천 영화가 표시돼요.")

# =============================
# UI Header
# =============================
st.title("🎬 나와 어울리는 영화는?")
st.write("5개의 질문에 답하면, 당신의 취향에 맞는 장르를 분석하고 TMDB 인기 영화 5편을 예쁘게 추천해줘요!")

# =============================
# Questions
# =============================
questions = [
    {
        "key": "q1",
        "text": "Q1. 시험이 끝난 금요일 밤, 가장 끌리는 계획은?",
        "choices": [
            ("A. 조용한 카페나 방에서 음악 들으며 하루를 정리한다", "로맨스/드라마"),
            ("B. 친구들이랑 갑자기 여행이나 밤샘 드라이브를 떠난다", "액션/어드벤처"),
            ("C. 게임·영화 보면서 다른 세계에 푹 빠진다", "SF/판타지"),
            ("D. 술자리나 수다로 웃다가 하루를 마무리한다", "코미디"),
        ],
    },
    {
        "key": "q2",
        "text": "Q2. 과제가 너무 많을 때, 너의 대처법은?",
        "choices": [
            ("A. 힘들지만 의미를 찾으며 묵묵히 해낸다", "로맨스/드라마"),
            ("B. “일단 부딪혀 보자!” 하면서 단번에 몰아서 끝낸다", "액션/어드벤처"),
            ("C. 나만의 방식으로 효율 루트를 연구한다", "SF/판타지"),
            ("D. 투덜대면서도 친구랑 농담 주고받으며 한다", "코미디"),
        ],
    },
    {
        "key": "q3",
        "text": "Q3. 영화 속 주인공이 된다면, 어떤 캐릭터가 좋을까?",
        "choices": [
            ("A. 감정선이 깊고 성장 서사가 있는 인물", "로맨스/드라마"),
            ("B. 위험한 상황에서도 앞장서는 히어로 타입", "액션/어드벤처"),
            ("C. 특별한 능력이나 비밀을 가진 존재", "SF/판타지"),
            ("D. 어디서든 분위기 살리는 인간 비타민", "코미디"),
        ],
    },
    {
        "key": "q4",
        "text": "Q4. 친구가 “너 요즘 어떤 상태야?”라고 물어본다면?",
        "choices": [
            ("A. 생각할 게 많고 감정이 조금 복잡해", "로맨스/드라마"),
            ("B. 뭔가 새로운 걸 해보고 싶어서 들떠 있어", "액션/어드벤처"),
            ("C. 머릿속에서 이것저것 상상 중이야", "SF/판타지"),
            ("D. 그냥 웃고 떠들면서 살고 있어", "코미디"),
        ],
    },
    {
        "key": "q5",
        "text": "Q5. 영화에서 가장 중요하게 보는 요소는?",
        "choices": [
            ("A. 공감되는 감정과 현실적인 이야기", "로맨스/드라마"),
            ("B. 긴장감 넘치는 전개와 스케일", "액션/어드벤처"),
            ("C. 세계관 설정과 상상력", "SF/판타지"),
            ("D. 얼마나 많이 웃을 수 있느냐", "코미디"),
        ],
    },
]

# =============================
# Helpers
# =============================
def short_text(text: str, n: int = 90) -> str:
    text = (text or "").strip()
    if not text:
        return "짧은 소개(줄거리) 정보가 없습니다."
    return text if len(text) <= n else text[:n].rstrip() + "…"

def ensure_all_answered(picks: List[Optional[str]]) -> bool:
    return all(p is not None for p in picks)

def analyze_genre_weighted(picks: List[str]) -> Tuple[str, Dict[str, int], str]:
    """
    고도화 포인트:
    - 가중치 점수(뒤 문항일수록 조금 더 가중) + 동점 타이브레이크(단순 카운트)
    """
    # 문항 중요도(예: 1~5번 점점 중요하게)
    weights = [1, 1, 2, 2, 3]

    score = Counter()
    raw = Counter(picks)

    for i, g in enumerate(picks):
        score[g] += weights[i]

    # 1) 가중치 점수 우선
    best_score = max(score.values())
    candidates = [g for g, s in score.items() if s == best_score]

    # 2) 동점이면 단순 선택 빈도
    if len(candidates) > 1:
        best_raw = max(raw[g] for g in candidates)
        candidates = [g for g in candidates if raw[g] == best_raw]

    # 3) 그래도 동점이면 고정 우선순위(원하는 취향대로 조절 가능)
    priority = ["로맨스/드라마", "액션/어드벤처", "SF/판타지", "코미디"]
    final = sorted(candidates, key=lambda x: priority.index(x))[0]

    reason_map = {
        "로맨스/드라마": "감정선·공감·성장 서사를 중시하는 선택이 많았어요.",
        "액션/어드벤처": "속도감과 도전/모험 감성에 끌리는 선택이 많았어요.",
        "SF/판타지": "세계관·상상력·몰입을 중요하게 여기는 선택이 많았어요.",
        "코미디": "웃음과 가벼운 텐션으로 스트레스를 푸는 쪽을 선호해요.",
    }
    return final, dict(score), reason_map.get(final, "선택 패턴을 기반으로 추천했어요.")

def tmdb_request_with_retry(
    session: requests.Session,
    url: str,
    params: dict,
    max_retries: int = 3,
    timeout: int = 15,
) -> dict:
    """
    429/일시 오류에 대한 간단 재시도(backoff).
    """
    backoff = 0.8
    last_err = None

    for attempt in range(max_retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                # Too Many Requests
                time.sleep(backoff)
                backoff *= 1.8
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            time.sleep(backoff)
            backoff *= 1.8

    raise RuntimeError(f"TMDB 요청 실패: {last_err}")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_discover_movies(api_key: str, with_genres: str, limit: int = 5) -> List[dict]:
    """
    Discover로 '인기' 기준 영화 가져오기 + 품질 필터.
    """
    session = requests.Session()
    params = {
        "api_key": api_key,
        "with_genres": with_genres,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "include_video": "false",
        "page": 1,
        # 너무 투표 수 적은 결과(정보 빈약/노이즈) 줄이기
        "vote_count.gte": 200,
    }
    data = tmdb_request_with_retry(session, TMDB_DISCOVER_URL, params=params)
    return (data.get("results") or [])[:limit]

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_movie_details(api_key: str, movie_id: int) -> dict:
    """
    append_to_response로 credits/videos를 한번에 붙여서 가져오기.
    """
    session = requests.Session()
    url = f"{TMDB_API_BASE}/movie/{movie_id}"
    params = {
        "api_key": api_key,
        "language": "ko-KR",
        "append_to_response": "credits,videos",
    }
    return tmdb_request_with_retry(session, url, params=params)

def build_recommend_reason(
    top_genre: str,
    base_reason: str,
    movie: dict,
    details: dict,
) -> str:
    """
    추천 이유를 '장르 매칭 + 평점/캐스트/감독/예고편' 단서로 짧게 구성.
    """
    rating = float(movie.get("vote_average") or 0.0)
    vote_count = int(movie.get("vote_count") or 0)

    # 감독/주연
    director = None
    cast_names = []
    credits = details.get("credits") or {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []

    for c in crew:
        if c.get("job") == "Director":
            director = c.get("name")
            break

    for c in cast[:2]:
        if c.get("name"):
            cast_names.append(c["name"])

    # 예고편 유무
    has_trailer = False
    videos = (details.get("videos") or {}).get("results") or []
    for v in videos:
        if (v.get("site") == "YouTube") and (v.get("type") in ["Trailer", "Teaser"]):
            has_trailer = True
            break

    bits = [base_reason]

    if rating >= 7.5 and vote_count >= 200:
        bits.append("평점/반응도 좋은 편이라 만족도가 높을 확률이 커요.")
    else:
        bits.append("요즘 인기작이라 가볍게 즐기기 좋아요.")

    if director:
        bits.append(f"감독: {director}.")
    if cast_names:
        bits.append(f"주연: {', '.join(cast_names)}.")
    if has_trailer:
        bits.append("예고편/영상도 있어 ‘찍먹’하기 좋아요.")

    # 너무 길어지면 컷
    reason = " ".join(bits)
    return reason if len(reason) <= 170 else reason[:170].rstrip() + "…"

def render_movie_card(movie: dict, emoji: str, reason: str):
    title = movie.get("title") or "제목 없음"
    rating = float(movie.get("vote_average") or 0.0)
    poster_path = movie.get("poster_path")
    overview = short_text(movie.get("overview"), 95)

    with st.container(border=True):
        if poster_path:
            st.image(POSTER_BASE_URL + poster_path, use_container_width=True)
        else:
            st.write("🖼️ 포스터 없음")

        st.markdown(f"### {emoji} {title}")
        st.write(f"⭐ **{rating:.1f}** / 10")
        st.caption(overview)
        st.markdown(f"**추천 이유:** {reason}")

# =============================
# Survey (form)
# =============================
answers = []

with st.form("quiz_form"):
    for q in questions:
        labels = [f"{t} ({g})" for t, g in q["choices"]]
        picked = st.radio(q["text"], labels, index=None, key=q["key"])
        if picked is None:
            answers.append(None)
        else:
            answers.append(picked.split("(")[-1].replace(")", "").strip())

    submitted = st.form_submit_button("결과 보기", type="primary")

# =============================
# Results
# =============================
if submitted:
    if not api_key:
        st.error("사이드바에 TMDB API Key를 입력해주세요.")
        st.stop()

    if not ensure_all_answered(answers):
        st.warning("5개 질문에 모두 답해야 결과를 볼 수 있어요!")
        st.stop()

    top_genre, score_map, base_reason = analyze_genre_weighted(answers)
    emoji = GENRE_EMOJI.get(top_genre, "🎬")
    title_genre = GENRE_TITLE.get(top_genre, top_genre)

    with st.spinner("분석 중... TMDB에서 인기 영화를 가져오고 있어요!"):
        with_genres = WITH_GENRES_MAP[top_genre]
        movies = fetch_discover_movies(api_key, with_genres, limit=5)

        # 추천 이유를 고도화하기 위해 상세 정보도 가져오기(캐시 적용)
        detailed_list = []
        for m in movies:
            mid = m.get("id")
            if not mid:
                detailed_list.append((m, {}))
                continue
            details = fetch_movie_details(api_key, int(mid))
            detailed_list.append((m, details))

    # 1) 요구사항: 결과 제목
    st.markdown(f"# 당신에게 딱인 장르는: **{emoji} {title_genre}**!")
    st.caption(base_reason)

    # (선택) 디버그/설명용 점수표를 보고 싶으면 주석 해제
    # st.write("점수표:", score_map)

    if not movies:
        st.warning("추천 영화를 찾지 못했어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    st.write("")  # spacing

    # 2) 요구사항: 3열 카드 레이아웃
    cols = st.columns(3)
    for idx, (movie, details) in enumerate(detailed_list):
        reason = build_recommend_reason(top_genre, base_reason, movie, details)
        with cols[idx % 3]:
            render_movie_card(movie, emoji, reason)
