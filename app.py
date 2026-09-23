"""Демо-интерфейс на Streamlit: streamlit run app.py

Собран для защиты: слева видно, какие инструменты агент дёрнул —
жюри сразу понимает, что внутри агент, а не обёртка над чатом.
"""

import streamlit as st

import agent
import llm
import tools

st.set_page_config(page_title="AI-агент", page_icon="*", layout="wide")

with st.sidebar:
    st.subheader("Под капотом")
    st.caption("Модель: `{}`".format(llm.MODEL))
    st.caption("Инструменты: " + ", ".join("`{}`".format(t) for t in tools.REGISTRY))
    st.divider()
    st.subheader("Что делал агент")
    trace_box = st.container()
    st.divider()
    if st.button("Показать расход токенов"):
        st.code(llm.usage_report())

st.title("AI-агент")
st.caption("Замените заголовок и системный промпт под своё задание.")

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.trace = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Поставьте агенту задачу"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Агент работает..."):
            answer, trace = agent.run(prompt, verbose=False)
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.trace = trace

with trace_box:
    if st.session_state.get("trace"):
        for row in st.session_state.trace:
            st.markdown("**{}**".format(row["tool"]))
            st.code("{}\n-> {}".format(row["args"], row["result"]), language="json")
    else:
        st.caption("Пока пусто.")
