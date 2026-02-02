import time
import requests
import streamlit as st
from collections import Counter
from typing import Dict, List, Optional, Tuple

# =============================
# Page
# =============================
st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="wide")

# =============================
# TMDB Constants
# =============================
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_DISCOVER_URL = f"{TMDB_API_BASE}/discover/movie"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

# 사용자의 4분류 선택 -> TMDB 장르 조합(OR)
WITH_GENRES_MAP = {
    "로맨스/드라마": "10749|18",
    "액션/어드벤처": "28",
    "SF/판타지": "878|14",
    "코미디": "35",
}

# 결과/카드 이모지
GENRE_EMOJI = {
    "로맨스/드라마": "💘🎭",
    "액션/어드벤처": "🔥🧗",
    "SF/판타지": "🛸🧙‍♂️",
    "코미디": "🤣🎈",
}

# 장르별 “원하는 톤”을 더 맞추기 위한 추가 필터(고도화 핵심)
# - 로맨스/드라마: 액션/호러/범죄 같은 강한 장르를 "exclude" 해서 결이 다른 영화 섞이는 걸 줄임
# - SF/판타지: 전쟁/서부 같은 건 제외
# - 코미디: 호러 제외
# - 액션: 가족/로맨스 과다 혼합 방지(완전히 배제할 필요는 없지만, 너무 섞이면 “안 어울림” 체감이 커짐)
EXCLUDE_GENRES_MAP = {
    "로맨스/드라마": "27,28,53,80,99,10752,37",  # 호러,액션,스릴러,범죄,다큐,전쟁,서부
    "SF/판타지": "37,10752,99",                  # 서부,전쟁,다큐
    "코미디": "27,53",                             # 호러,스릴러
    "액션/어드벤처": "99",                         # 다큐
}

# =============================
# Sidebar
# =============================
st.sidebar.header("🔑 TMDB 설정")
api_key = st.sidebar.text_input("TMDB API Key", type="password")
strict_mode = st.sidebar.toggle("장르 일치 강화(엄격 추천)", value=True)
st.sidebar.caption("‘엄격 추천’을 켜면 선택한 장르와 결이 다른 영화가 섞이는 현상을 줄여줘요.")

# =============================
# Header
# =============================
st.title("🎬 나와 어울리는 영화는?")
st.write("5개의 질문에 답하면, 당신의 취향에 맞는 장르를 분석하고 TMDB 인기 영화 5편을 추천해줘요!")

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
def short_text(text: str, n: int = 95) -> str:
    text = (text or "").strip()
    if not text:
        return "짧은 소개(줄거리) 정보가 없습니다."
    return text if len(text) <= n else text[:n].rstrip() + "…"


def ensure_all_answered(picks: List[Optional[str]]) -> bool:
    return all(p is not None for p in picks)


def analyze_genre_simple(picks: List[str]) -> Tuple[str, Dict[str, int], str]:
    """
    ✅ 심리검사와 결과가 “직접” 연결되도록:
    - 가중치 없이 '단순 최다 선택'을 1순위로 사용
    - 동점일 때만 마지막 문항(5번) 선택을 타이브레이커로 사용
    """
    counts = Counter(picks)
    most = counts.most_common()

    top_count = most[0][1]
    candidates = [g for g, c in most if c == top_count]

    if len(candidates) == 1:
        final = candidates[0]
    else:
        # 동점이면 5번 문항 선택을 우선(가장 “요소” 선호가 확실한 질문)
        final = picks[-1] if picks[-1] in candidates else candidates[0]

    reason_map = {
        "로맨스/드라마": "공감되는 감정과 현실적인 이야기(감정선·성장)를 선호하는 선택이 많았어요.",
        "액션/어드벤처": "긴장감 있는 전개와 도전/모험 감성을 선호하는 선택이 많았어요.",
        "SF/판타지": "상상력 넘치는 세계관과 몰입을 선호하는 선택이 많았어요.",
        "코미디": "웃음 포인트로 스트레스를 푸는 쪽을 선호하는 선택이 많았어요.",
    }
    return final, dict(counts), reason_map.get(final, "선택 패턴을 기반으로 추천했어요.")


def tmdb_request(url: str, params: dict, max_retries: int = 3, timeout: int = 15):
    backoff = 0.8
    last_error = ""
    last_status = None

    for _ in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            last_status = r.status_code

            if r.status_code == 429:
                last_error = "요청이 너무 많아요(429). 잠시 후 다시 시도해주세요."
                time.sleep(backoff)
                backoff *= 1.8
                continue

            if r.status_code in (401, 403):
                return False, None, "API Key가 유효하지 않거나 권한이 없어요(401/403).", r.status_code

            r.raise_for_status()
            return True, r.json(), "", r.status_code

        except requests.exceptions.Timeout:
            last_error = "TMDB 요청 시간이 초과됐어요(Timeout)."
        except requests.exceptions.ConnectionError:
            last_error = "네트워크 연결 오류가 발생했어요(ConnectionError)."
        except requests.exceptions.HTTPError:
            last_error = f"TMDB 서버 응답 오류(HTTP {last_status})."
        except requests.exceptions.RequestException as e:
            last_error = f"요청 오류: {type(e).__name__}"

        time.sleep(backoff)
        backoff *= 1.8

    return False, None, last_error or "TMDB 요청에 실패했어요.", last_status


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_discover_movies_cached(api_key: str, with_genres: str, strict: bool, limit: int = 5) -> List[dict]:
    """
    ✅ 장르 일치 강화 핵심:
    - strict=True: with_genres + without_genres + 최소 투표수 + 인기순
    - strict=False: with_genres만으로 넓게 추천
    """
    params = {
        "api_key": api_key,
        "with_genres": with_genres,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "include_video": "false",
        "page": 1,
    }

    if strict:
        # 투표 수가 너무 적은 경우 “장르 느낌이 안 맞는” 결과가 섞이는 체감이 커서 최소치 부여
        params["vote_count.gte"] = 150
        # 결이 다른 장르 제외(핵심)
        # (TMDB Discover에서 without_genres 지원)
        # strict 모드에서는 “로맨스만 골랐는데 액션/호러 섞임” 같은 상황이 크게 줄어듦
        params["without_genres"] = EXCLUDE_GENRES_MAP.get("로맨스/드라마", "")

    ok, data, err, status = tmdb_request(TMDB_DISCOVER_URL, params=params)
    if not ok or not data:
        return []
    return (data.get("results") or [])[:limit]


def fetch_movies_with_correct_filters(api_key: str, top_genre: str, strict: bool, limit: int = 5):
    """
    ✅ BUG FIX:
    이전 코드에서 strict 모드일 때 without_genres가 '로맨스/드라마'로 고정되는 실수가 생기기 쉬움.
    여기서는 top_genre에 맞춰 정확히 적용.
    """
    with_genres = WITH_GENRES_MAP[top_genre]

    params = {
        "api_key": api_key,
        "with_genres": with_genres,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "include_video": "false",
        "page": 1,
    }

    if strict:
        params["vote_count.gte"] = 150
        params["without_genres"] = EXCLUDE_GENRES_MAP.get(top_genre, "")

    ok, data, err, status = tmdb_request(TMDB_DISCOVER_URL, params=params)
    if not ok:
        return [], err
    results = (data.get("results") or [])[:limit]
    if not results:
        # strict 때문에 너무 좁으면, strict 해제 폴백
        if strict:
            params.pop("without_genres", None)
            params.pop("vote_count.gte", None)
            ok2, data2, err2, status2 = tmdb_request(TMDB_DISCOVER_URL, params=params)
            if not ok2:
                return [], err2
            results2 = (data2.get("results") or [])[:limit]
            if results2:
                return results2, ""
            return [], "조건에 맞는 영화를 찾지 못했어요."
        return [], "조건에 맞는 영화를 찾지 못했어요."
    return results, ""


def build_reason(base_reason: str, movie: dict, top_genre: str) -> str:
    rating = float(movie.get("vote_average") or 0.0)
    vote_count = int(movie.get("vote_count") or 0)

    # 장르별 “추천 문구 톤”을 더 맞춤
    extra_map = {
        "로맨스/드라마": "감정선이 살아있는 이야기라 몰입하기 좋아요.",
        "액션/어드벤처": "전개가 빠르고 긴장감 있는 편이라 시원하게 보기 좋아요.",
        "SF/판타지": "세계관이 매력적이라 ‘다른 세계’로 떠나는 느낌을 줘요.",
        "코미디": "웃음 포인트가 많아서 가볍게 스트레스 풀기 좋아요.",
    }

    quality = "평점/반응도도 꽤 좋아 만족도가 높을 확률이 커요." if (rating >= 7.2 and vote_count >= 200) else "요즘 인기작이라 접근하기 쉬워요."
    text = f"{base_reason} {extra_map.get(top_genre, '')} {quality}"
    return text if len(text) <= 170 else text[:170].rstrip() + "…"


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
answers: List[Optional[str]] = []

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

    picks = [a for a in answers if a is not None]

    # ✅ “다 로맨스/드라마 찍었는데도 이상한 장르 추천” 방지:
    # - 단순 최다 선택으로 장르를 결정(가중치 제거)
    top_genre, counts, base_reason = analyze_genre_simple(picks)
    emoji = GENRE_EMOJI.get(top_genre, "🎬")

    with st.spinner("분석 중... TMDB에서 인기 영화를 가져오는 중!"):
        movies, err = fetch_movies_with_correct_filters(api_key, top_genre, strict_mode, limit=5)

    if err:
        st.error(f"TMDB 추천을 가져오지 못했어요: {err}")
        st.stop()

    if not movies:
        st.warning("추천 영화를 찾지 못했어요. 잠시 후 다시 시도해 주세요.")
        st.stop()

    st.markdown(f"# 당신에게 딱인 장르는: **{emoji} {top_genre}**!")
    st.caption(base_reason)
    st.write("")

    cols = st.columns(3)
    for idx, movie in enumerate(movies):
        why = build_reason(base_reason, movie, top_genre)
        with cols[idx % 3]:
            render_movie_card(movie, emoji, why)
