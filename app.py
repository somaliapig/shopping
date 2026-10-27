"""쇼핑 리스트 Streamlit 앱 진입점. UI만 담당한다.

- 목록은 세션에 캐시하지 않고 매 rerun마다 파일에서 읽는다. 변경은 storage.update_items()로
  "최신 파일 읽기 → 변경 → 저장"을 한 번에 해서 다른 탭/사용자의 변경을 덮어쓰지 않는다.
- 버튼/체크박스는 on_click·on_change 콜백으로 상태를 바꾼다. 위젯 key는 모두 item.id 기반이라
  삭제 후에도 상태가 꼬이지 않는다.
- 입력 범위(이름 100자, 수량 1~999)는 위젯이 아니라 services가 검증한다. 위젯에 제한을 걸면
  Streamlit이 잘못된 입력을 조용히 버려서 사용자가 이유를 알 수 없다.
"""

import re
from pathlib import Path
from typing import Callable

import streamlit as st

import services
from models import Item
from storage import load_items, update_items

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")

STYLE_PATH = Path(__file__).parent / "assets" / "style.css"
st.markdown(f"<style>{STYLE_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

FILTER_LABELS = {"all": "전체", "active": "미완료", "done": "완료"}
SAVE_FAILED = "저장하지 못했어요. 잠시 후 다시 시도해주세요"

# ---------------------------------------------------------------- 상태 관리

st.session_state.setdefault("editing_id", None)
st.session_state.setdefault("edit_error", None)
if st.session_state.get("filter") not in FILTER_LABELS:
    st.session_state.filter = "all"


def flash(message: str, icon: str = "✅") -> None:
    """콜백 안에서는 토스트를 바로 띄우지 않고 다음 렌더링으로 예약한다."""
    st.session_state.flash = (message, icon)


def mutate(change: Callable[[list[Item]], list[Item]], message: str | None = None, icon: str = "✅") -> str:
    """콜백용 변경 헬퍼. 'ok' / 'missing'(다른 곳에서 이미 삭제됨) / 'failed'(저장 실패)를 반환한다.

    change가 던지는 ValueError(입력 검증 실패)는 호출한 쪽에서 처리하도록 그대로 전달한다.
    """
    try:
        update_items(change)
    except KeyError:
        flash("다른 곳에서 이미 삭제된 항목이에요", "ℹ️")
        return "missing"
    except OSError:
        flash(SAVE_FAILED, "⚠️")
        return "failed"
    if message:
        flash(message, icon)
    return "ok"


def escape_md(text: str) -> str:
    """사용자 입력이 마크다운 문법으로 해석되지 않도록 특수문자를 이스케이프한다."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>$:])", r"\\\1", text)


# ---------------------------------------------------------------- 콜백


def on_toggle(item_id: str) -> None:
    mutate(lambda items: services.toggle_item(items, item_id))


def on_delete(item_id: str) -> None:
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None
    deleted: list[Item] = []

    def change(items: list[Item]) -> list[Item]:
        deleted.extend(i for i in items if i.id == item_id)
        if not deleted:
            raise KeyError(item_id)
        return services.delete_item(items, item_id)

    if mutate(change) == "ok":
        flash(f"'{escape_md(deleted[0].name)}'을(를) 삭제했어요", "🗑️")


def on_start_edit(item_id: str) -> None:
    st.session_state.editing_id = item_id
    st.session_state.edit_error = None


def on_cancel_edit() -> None:
    st.session_state.editing_id = None
    st.session_state.edit_error = None


def on_save_edit(item_id: str) -> None:
    name = st.session_state.get(f"edit_name_{item_id}", "")
    quantity = st.session_state.get(f"edit_qty_{item_id}", 1)
    try:
        result = mutate(lambda items: services.update_item(items, item_id, name, quantity), "수정했어요", "✏️")
    except ValueError as e:
        st.session_state.edit_error = str(e)
        return
    if result != "failed":
        st.session_state.editing_id = None
        st.session_state.edit_error = None


def on_clear_checked() -> None:
    cleared: list[int] = []

    def change(items: list[Item]) -> list[Item]:
        cleared.append(services.get_stats(items)["done"])
        return services.clear_checked(items)

    if mutate(change) == "ok" and cleared[0]:
        flash(f"완료 항목 {cleared[0]}개를 삭제했어요", "🧹")


# ---------------------------------------------------------------- 화면

if message := st.session_state.pop("flash", None):
    st.toast(message[0], icon=message[1])

header = st.container(key="header")  # 추가 처리 후 최신 통계로 채운다

# 입력 영역
with st.form("add_form", clear_on_submit=True, border=False):
    with st.container(key="add_row", horizontal=True, vertical_alignment="bottom", gap="small"):
        new_name = st.text_input(
            "아이템 이름",
            placeholder="무엇을 사야 하나요? (예: 우유)",
            label_visibility="collapsed",
        )
        new_qty = st.number_input(
            "수량", value=1, step=1, label_visibility="collapsed", width=110
        )
        submitted = st.form_submit_button("추가", type="primary", width="content")

if submitted:
    duplicate: list[bool] = []

    def add_change(items: list[Item]) -> list[Item]:
        duplicate.append(services.has_duplicate(items, new_name))
        return services.add_item(items, new_name, int(new_qty))

    try:
        update_items(add_change)
    except ValueError as e:
        st.error(str(e))
    except OSError:
        st.error(SAVE_FAILED)
    else:
        clean_name = escape_md(new_name.strip())
        if duplicate[0]:
            st.toast(f"'{clean_name}'은(는) 이미 목록에 있어요. 그래도 추가했어요", icon="⚠️")
        else:
            st.toast(f"'{clean_name}'을(를) 추가했어요", icon="✅")

items = load_items()
stats = services.get_stats(items)
if st.session_state.editing_id not in {i.id for i in items}:
    st.session_state.editing_id = None  # 다른 곳에서 삭제된 항목을 편집 중이었으면 닫는다

# 헤더: 제목 + 진행률
with header:
    st.title("🛒 쇼핑 리스트")
    ratio = stats["done"] / stats["total"] if stats["total"] else 0.0
    st.progress(ratio, text=f"{stats['done']}/{stats['total']} 완료")

# 목록 영역
visible = services.filter_items(items, st.session_state.filter)

if not items:
    with st.container(key="empty"):
        st.markdown("장볼 목록을 추가해보세요 🛒")
        st.caption("위 입력창에 아이템 이름을 적고 Enter를 누르세요")
elif not visible:
    with st.container(key="empty"):
        st.markdown(f"'{FILTER_LABELS[st.session_state.filter]}' 항목이 없어요")

for item in visible:
    if st.session_state.editing_id == item.id:
        with st.container(key=f"editing_{item.id}"):
            with st.form(f"edit_form_{item.id}", border=False):
                with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                    st.text_input("이름 수정", value=item.name, key=f"edit_name_{item.id}")
                    st.number_input(
                        "수량 수정", value=item.quantity, step=1, key=f"edit_qty_{item.id}", width=110
                    )
                if st.session_state.edit_error:
                    st.error(st.session_state.edit_error)
                with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
                    st.form_submit_button("취소", on_click=on_cancel_edit)
                    st.form_submit_button(
                        "저장", type="primary", on_click=on_save_edit, args=(item.id,)
                    )
        continue

    # 완료 여부를 key에 넣어 CSS로 카드 스타일을 바꾼다 (위젯 key는 item.id만 써서 상태는 유지된다)
    state = "done" if item.checked else "todo"
    name_md = escape_md(item.name)
    with st.container(
        key=f"row_{state}_{item.id}", horizontal=True, vertical_alignment="center", gap="small"
    ):
        # 다른 탭에서 바뀐 체크 상태가 이 세션의 위젯 값에 덮이지 않도록 파일 값으로 맞춘다
        st.session_state[f"chk_{item.id}"] = item.checked
        st.checkbox(
            f"{item.name} 구매 완료",  # 숨겨진 라벨이라 이스케이프하지 않는다 (aria-label로 그대로 읽힘)
            key=f"chk_{item.id}",
            label_visibility="collapsed",
            on_change=on_toggle,
            args=(item.id,),
            width="content",
        )
        st.text(item.name, width="stretch")  # 마크다운/자동 링크 없이 글자 그대로 표시
        badge = "gray" if item.checked else "orange"
        st.markdown(f":{badge}-badge[× {item.quantity}]", width="content")
        # 버튼 글자는 CSS로 시각적으로만 숨겨 아이콘만 보이고, 스크린리더는 "<이름> 수정"으로 읽는다
        st.button(
            f"{name_md} 수정", icon="✏️", key=f"edit_{item.id}", help=f"'{name_md}' 수정",
            type="tertiary", on_click=on_start_edit, args=(item.id,),
        )
        st.button(
            f"{name_md} 삭제", icon="🗑️", key=f"del_{item.id}", help=f"'{name_md}' 삭제",
            type="tertiary", on_click=on_delete, args=(item.id,),
        )

# 하단: 필터, 통계, 완료 항목 삭제
# 필터 라벨은 고정값이어야 한다. format_func 결과가 바뀌면 Streamlit이 선택값을 잃어버린다.
with st.container(
    key="footer", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
):
    st.segmented_control(
        "필터",
        options=list(FILTER_LABELS),
        format_func=FILTER_LABELS.get,
        key="filter",
        required=True,
        label_visibility="collapsed",
    )
    st.caption(f"전체 {stats['total']} · 남은 {stats['active']} · 완료 {stats['done']}")
    st.button(
        "완료 항목 삭제",
        icon="🧹",
        disabled=stats["done"] == 0,
        help="체크한 항목을 모두 지워요",
        on_click=on_clear_checked,
    )
