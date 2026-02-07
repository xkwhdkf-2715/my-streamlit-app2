import os
import time
import streamlit as st
from openai import OpenAI

# =========================
# Page
# =========================
st.set_page_config(
    page_title="내가 선호하는 국내 여행지는?",
    page_icon="🧳",
    layout="centered"
)

# =========================
# Sidebar: OpenAI Key
# =========================
st.sidebar.header("🔑 OpenAI 설정")

user_api_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    help="OpenAI API 키를 입력하면 챗봇이 활성화됩니다."
)

st.sidebar.caption("키는 저장되지 않고, 이 앱 실행 중에만 사용돼요.")

# 환경 변수 기본값도 허용 (선택)
env_api_key = os.getenv("OPENAI_API_KEY", "")

# 우선순위: 사이드바 입력 > 환경변수
api_key = user_api_key if user_api_key else env_api_key

# =========================
# Main UI
# =========================
st.title("내가 선호하는 국내 여행지는?")
st.caption("간단한 선호도 조사 + 추가 정보(예산/기간/스타일)를 채팅으로 입력하면 나중에 더 정확한 추천이 가능해져요!")

# =========================
# Survey
# =========================
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

# =========================
# Session State (Chat)
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "좋아요! 😊\n예산, 여행 기간(몇박 몇일), 출발 지역, 하고 싶은 것(맛집/바다/산/감성카페 등)을 편하게 말해줘요!"
        }
    ]

# =========================
# Show Chat History
# =========================
st.subheader("💬 추가 정보 입력 (챗봇)")
st.caption("여기서 입력한 내용은 나중에 여행지 추천 결과를 만들 때 반영할 수 있어요.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# =========================
# OpenAI Streaming Function
# =========================
def stream_openai_response(client: OpenAI, messages: list):
    """
    OpenAI 스트리밍 응답을 받아서 Streamlit에 타이핑 효과로 출력
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        stream=True,
    )

    full_text = ""
    placeholder = st.empty()

    for chunk in response:
        if chunk.choices and chunk.choices[0].delta:
            delta = chunk.choices[0].delta.content
            if delta:
                full_text += delta
                placeholder.markdown(full_text)
                time.sleep(0.01)

    return full_text

# =========================
# Chat Input
# =========================
user_input = st.chat_input("예: 예산 20만원, 1박2일, 서울 출발, 바다+맛집 위주로!")

if user_input:
    # 1) 유저 메시지 저장
    st.session_state.messages.append({"role": "user", "content": user_input})

    # 2) 화면에 유저 메시지 출력
    with st.chat_message("user"):
        st.write(user_input)

    # 3) OpenAI Key 확인
    if not api_key:
        with st.chat_message("assistant"):
            st.error("OpenAI API Key가 없어요! 사이드바에 입력해 주세요.")
        st.stop()

    # 4) OpenAI 호출
    client = OpenAI(api_key=api_key)

    # 시스템 프롬프트(중요!)
    system_prompt = """
너는 국내 여행지 추천을 위한 정보 수집용 챗봇이야.
사용자가 입력하는 예산, 여행 기간, 출발지, 선호 활동(맛집/자연/카페/액티비티), 숙소 스타일 등을 자연스럽게 파악하고,
추가로 필요한 정보가 있으면 질문해.

중요:
- 지금은 여행지 결과를 추천하지 말 것.
- 사용자의 정보를 더 정확히 얻기 위한 질문만 할 것.
- 말투는 친근하고 간단하게.
"""

    # 설문 결과를 대화 컨텍스트에 포함
    survey_context = f"""
[현재 사용자의 선택]
- 여행 목적: {q1}
- 동반자: {q2}
- 이동수단: {q3}
"""

    messages_for_api = [{"role": "system", "content": system_prompt}]
    messages_for_api.append({"role": "system", "content": survey_context})
    messages_for_api.extend(st.session_state.messages)

    # 5) 스트리밍 출력
    with st.chat_message("assistant"):
        try:
            assistant_text = stream_openai_response(client, messages_for_api)
        except Exception as e:
            st.error("OpenAI 요청 중 오류가 발생했어요.")
            st.caption(str(e))
            st.stop()

    # 6) 어시스턴트 메시지 저장
    st.session_state.messages.append({"role": "assistant", "content": assistant_text})

# =========================
# 결과 보기 버튼 (아직 결과는 만들지 않음)
# =========================
st.divider()

if st.button("결과 보기", type="primary"):
    if q1 is None or q2 is None or q3 is None:
        st.warning("모든 질문에 답해야 결과를 볼 수 있어요!")
    else:
        st.info("지금은 결과 화면을 아직 만들지 않았어요! 😊\n대신 위 채팅으로 예산/기간 같은 정보를 입력해두면 다음 단계에서 추천에 반영할 수 있어요.")
