import base64
from pathlib import Path


CHROME_CSS = r"""
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stMainMenu"],
[data-testid="stAppToolbar"],
.stDeployButton,
#MainMenu { display: none !important; visibility: hidden !important; }
[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
"""

TOPBAR_CSS = r"""
div[data-testid="element-container"]:has(.app-topbar),
div[data-testid="stElementContainer"]:has(.app-topbar) {
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: visible !important;
}
.app-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 52px;
  z-index: 99990;
  display: flex;
  align-items: center;
  padding: 0 168px 0 18px;
  background: linear-gradient(180deg, rgba(10,30,46,.96), rgba(6,21,34,.98));
  border-bottom: 1px solid #21445f;
  box-shadow: 0 10px 28px rgba(0,0,0,.22);
  backdrop-filter: blur(16px);
  pointer-events: none;
}
.app-topbar-user,
.app-topbar-account {
  pointer-events: auto;
}
.app-topbar-user {
  color: #e8f0f6;
  font-size: 13px;
  font-weight: 650;
  letter-spacing: .04em;
}
.app-topbar-account {
  margin-left: 8px;
  color: #91a6b8;
  font-weight: 500;
  font-size: 12px;
}
div[data-testid="element-container"]:has(.topbar-dots),
div[data-testid="stElementContainer"]:has(.topbar-dots),
div[data-testid="element-container"]:has(.nav-history),
div[data-testid="element-container"]:has(.page-mode-history),
div[data-testid="element-container"]:has(.page-mode-research),
div[data-testid="element-container"]:has(.title-new),
div[data-testid="element-container"]:has(.history-hero-anchor),
div[data-testid="stElementContainer"]:has(.nav-history),
div[data-testid="stElementContainer"]:has(.page-mode-history),
div[data-testid="stElementContainer"]:has(.page-mode-research),
div[data-testid="stElementContainer"]:has(.title-new),
div[data-testid="stElementContainer"]:has(.history-hero-anchor) {
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}
div[data-testid="element-container"]:has(.topbar-dots) + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.topbar-dots) + div[data-testid="stElementContainer"] {
  position: fixed !important;
  top: 7px !important;
  right: 12px !important;
  left: auto !important;
  z-index: 100050 !important;
  width: auto !important;
  min-width: 0 !important;
  height: auto !important;
  overflow: visible !important;
}
[data-testid="stPopover"] {
  position: fixed !important;
  top: 7px !important;
  right: 12px !important;
  left: auto !important;
  z-index: 100050 !important;
  width: auto !important;
  overflow: visible !important;
}
[data-testid="stPopover"] > button {
  width: 38px !important;
  min-width: 38px !important;
  max-width: 38px !important;
  min-height: 38px !important;
  height: 38px !important;
  padding: 0 0 0 11px !important;
  border-radius: 9px !important;
  font-size: 22px !important;
  letter-spacing: 0;
  line-height: 1;
  color: #dce8f0 !important;
  background: #0c263a !important;
  border: 1px solid #315871 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: flex-start !important;
  gap: 0 !important;
  overflow: hidden !important;
}
[data-testid="stPopover"] > button:hover {
  border-color: #5b87a3 !important;
  background: #12344d !important;
}
div[data-testid="element-container"]:has(.nav-history) + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.nav-history) + div[data-testid="stElementContainer"] {
  position: fixed !important;
  top: 7px;
  right: 58px;
  z-index: 100049;
  width: auto !important;
  min-width: 0 !important;
}
div[data-testid="element-container"]:has(.nav-history) + div[data-testid="element-container"] button,
div[data-testid="stElementContainer"]:has(.nav-history) + div[data-testid="stElementContainer"] button {
  min-height: 36px !important;
  height: 36px !important;
  padding: 0 14px !important;
  font-size: 13px !important;
  border-radius: 8px !important;
}
.history-page-title { margin: 0; }
div[data-testid="element-container"]:has(.title-new) + div[data-testid="element-container"] button,
div[data-testid="stElementContainer"]:has(.title-new) + div[data-testid="stElementContainer"] button {
  min-height: 36px !important;
  height: 36px !important;
  margin-top: 2px !important;
}
div[data-testid="stDialog"] div[role="dialog"] {
  border: 1px solid #c6a15b;
  border-radius: 12px;
}
div[data-testid="element-container"]:has(.top-stagebar),
div[data-testid="stElementContainer"]:has(.top-stagebar) {
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: visible !important;
}
.top-stagebar {
  position: fixed;
  top: 7px;
  left: 50%;
  z-index: 100000;
  height: 38px;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  pointer-events: none;
}
.top-stage {
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 11px 0 7px;
  border: 1px solid rgba(49,88,113,.72);
  border-radius: 999px;
  background: rgba(8,27,43,.72);
  color: #7f96a8;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .02em;
}
.top-stage-num {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #91a6b8;
  background: rgba(125,183,221,.09);
  border: 1px solid rgba(91,135,163,.42);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.top-stage.current {
  color: #f1f6fa;
  border-color: #c6a15b;
  background: linear-gradient(180deg, rgba(47,70,84,.94), rgba(24,49,65,.96));
  box-shadow: 0 0 0 1px rgba(198,161,91,.12), 0 5px 16px rgba(0,0,0,.18);
}
.top-stage.current .top-stage-num {
  color: #071b2c;
  background: #c6a15b;
  border-color: #d4b878;
}
.top-stage.done {
  color: #b9cad6;
  border-color: rgba(91,135,163,.74);
  background: rgba(16,48,70,.86);
}
.top-stage.done .top-stage-num {
  color: #dce8f0;
  border-color: #5b87a3;
  background: rgba(61,111,143,.55);
}
.top-stage-connector {
  width: 24px;
  height: 1px;
  margin: 0 5px;
  background: #315871;
}
.top-stage-connector.done,
.top-stage-connector.current {
  background: linear-gradient(90deg, #5b87a3, #c6a15b);
}
[data-testid="stMainBlockContainer"]:has(.page-mode-research),
.main .block-container:has(.page-mode-research) {
  padding-top: 4.4rem;
  padding-left: clamp(28px, 5vw, 80px);
  padding-right: clamp(28px, 5vw, 80px);
}
.llm-drawer-state,
.llm-drawer-anchor {
  width: 1px;
  height: 1px;
}
div[data-testid="element-container"]:has(.llm-drawer-state),
div[data-testid="stElementContainer"]:has(.llm-drawer-state),
div[data-testid="element-container"]:has(.llm-drawer-anchor),
div[data-testid="stElementContainer"]:has(.llm-drawer-anchor) {
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: visible !important;
}
div[data-testid="element-container"]:has(.llm-drawer-state) + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.llm-drawer-state) + div[data-testid="stElementContainer"] {
  position: fixed !important;
  top: 50% !important;
  right: 0 !important;
  z-index: 99994 !important;
  width: 36px !important;
  min-width: 36px !important;
  transform: translateY(-50%) !important;
  transition: right .32s cubic-bezier(.22, 1, .36, 1) !important;
}
div[data-testid="element-container"]:has(.llm-drawer-state.is-open) + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.llm-drawer-state.is-open) + div[data-testid="stElementContainer"] {
  right: 360px !important;
}
div[data-testid="element-container"]:has(.llm-drawer-state) + div[data-testid="element-container"] button,
div[data-testid="stElementContainer"]:has(.llm-drawer-state) + div[data-testid="stElementContainer"] button {
  width: 36px !important;
  min-width: 36px !important;
  max-width: 36px !important;
  height: 50px !important;
  min-height: 50px !important;
  padding: 0 !important;
  border-radius: 12px 0 0 12px !important;
  font-size: 20px !important;
  line-height: 1 !important;
  color: #dce8f0 !important;
  background:
    radial-gradient(circle at 35% 22%, rgba(125,183,221,.30), transparent 46%),
    linear-gradient(145deg, rgba(18,60,92,.98), rgba(6,21,34,.98)) !important;
  border: 1px solid rgba(91,135,163,.86) !important;
  border-right: none !important;
  box-shadow: -2px 0 0 rgba(198,161,91,.26) inset, 0 10px 24px rgba(0,0,0,.26) !important;
}
div[data-testid="element-container"]:has(.llm-drawer-state) + div[data-testid="element-container"] button:hover,
div[data-testid="stElementContainer"]:has(.llm-drawer-state) + div[data-testid="stElementContainer"] button:hover {
  color: #ffe1a0 !important;
  border-color: rgba(198,161,91,.78) !important;
  background:
    radial-gradient(circle at 35% 22%, rgba(198,161,91,.22), transparent 46%),
    linear-gradient(145deg, rgba(23,75,112,.98), rgba(8,29,46,.98)) !important;
}
div[data-testid="element-container"]:has(.llm-drawer-anchor) + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.llm-drawer-anchor) + div[data-testid="stElementContainer"] {
  position: fixed !important;
  top: 60px !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 360px !important;
  z-index: 99988 !important;
  overflow-y: auto !important;
  padding: 18px 16px 20px !important;
  border-left: 1px solid rgba(49,88,113,.76) !important;
  background: linear-gradient(180deg, rgba(10,30,46,.98), rgba(6,21,34,.99)) !important;
  box-shadow: -20px 0 48px rgba(0,0,0,.26) !important;
  transform: translateX(100%) !important;
  transition: transform .32s cubic-bezier(.22, 1, .36, 1) !important;
}
div[data-testid="element-container"]:has(.llm-drawer-state.is-open) + div[data-testid="element-container"] + div[data-testid="element-container"] + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.llm-drawer-state.is-open) + div[data-testid="stElementContainer"] + div[data-testid="stElementContainer"] + div[data-testid="stElementContainer"] {
  transform: translateX(0) !important;
}
.main .block-container:has(.llm-drawer-state.is-open) {
  padding-right: 1rem;
}
.main .block-container:has(.llm-split-open) {
  max-width: none;
  padding-right: 1rem;
}
/* Streamlit 1.6x uses stMainBlockContainer instead of the legacy .main wrapper. */
[data-testid="stMainBlockContainer"]:has(.llm-split-open) {
  box-sizing: border-box !important;
  width: 66.667vw !important;
  max-width: 66.667vw !important;
  margin-left: 0 !important;
  margin-right: auto !important;
  padding-right: 18px !important;
  overflow-x: hidden !important;
}
div[data-testid="element-container"]:has(.llm-drawer-state.is-open) + div[data-testid="element-container"],
div[data-testid="stElementContainer"]:has(.llm-drawer-state.is-open) + div[data-testid="stElementContainer"] {
  right: calc(33.333vw - 18px) !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) {
  position: fixed !important;
  top: 52px !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 33.333vw !important;
  max-width: 33.333vw !important;
  z-index: 99970 !important;
  overflow: hidden !important;
  border-left: 1px solid rgba(91,135,163,.78);
  height: calc(100dvh - 52px) !important;
  min-height: 0 !important;
  padding: clamp(10px, 2vh, 22px) clamp(14px, 2.2vw, 34px) !important;
  background:
    radial-gradient(circle at 70% -8%, rgba(29,91,132,.28), transparent 38%),
    linear-gradient(180deg, #0a1e2e, #061522);
  box-shadow: -18px 0 42px rgba(0,0,0,.26);
}
div[data-testid="stColumn"]:has(.llm-chat-root) > div {
  position: relative !important;
  height: 100% !important;
  min-height: 0 !important;
  max-height: 100% !important;
  display: flex;
  flex-direction: column;
  width: 100% !important;
  overflow: hidden !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"],
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"] {
  width: 100% !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"]:has(.llm-empty),
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"]:has(.llm-empty) {
  flex: 1 1 auto;
  display: flex;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"]:has(.llm-empty) > div,
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"]:has(.llm-empty) > div {
  width: 100%;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"]:has(.llm-thinking),
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"]:has(.llm-thinking) {
  margin-top: auto !important;
}
.llm-title {
  color: var(--title);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: .02em;
  margin: 4px 0 8px;
}
.llm-header {
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:14px;
  padding-bottom:14px;
}
.llm-subtitle {
  color: var(--muted);
  font-size: 12px;
  margin-top: 3px;
}
.llm-badge {
  color: #b8c6d3;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(91,135,163,.42);
  background: rgba(8,27,43,.48);
}
.llm-welcome {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
  padding: 12px;
  border-radius: 12px;
  background: rgba(125,183,221,.08);
  border: 1px solid rgba(49,88,113,.50);
  margin-bottom: 14px;
}
.llm-empty {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
  border: 1px dashed rgba(91,135,163,.38);
  border-radius: 14px;
  background: rgba(8,27,43,.24);
  margin-bottom: 12px;
  text-align: center;
}
.llm-empty-title {
  color: var(--title);
  font-size: 18px;
  font-weight: 750;
  margin-bottom: 8px;
}
.llm-empty-sub {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
  max-width: 380px;
}
.llm-transcript {
  flex: 1 1 auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  min-height: 180px;
  height: calc(100vh - 386px);
  max-height: calc(100vh - 386px);
  padding: 8px 2px 22px;
  border-top: 1px solid rgba(49,88,113,.32);
}
.llm-transcript-anchor {
  height: 0;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"]:has(.llm-transcript-anchor),
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"]:has(.llm-transcript-anchor) {
  flex: 1 1 0 !important;
  min-height: 0 !important;
  height: auto !important;
  overflow: hidden !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stVerticalBlockBorderWrapper"]:has(.llm-transcript-anchor) {
  flex: 1 1 auto !important;
  min-height: 0 !important;
  height: auto !important;
  max-height: none !important;
  overflow-y: auto !important;
  overscroll-behavior: contain;
  border-top: 1px solid rgba(49,88,113,.32);
  padding-top: 8px;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stVerticalBlockBorderWrapper"]:has(.llm-transcript-anchor) > div {
  height: auto !important;
}
/* border=False containers use stLayoutWrapper in current Streamlit releases. */
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stLayoutWrapper"]:has(.llm-transcript-anchor) {
  flex: 1 1 0 !important;
  min-height: 0 !important;
  height: 0 !important;
  max-height: none !important;
  overflow: hidden !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stLayoutWrapper"]:has(.llm-transcript-anchor) > div[data-testid="stVerticalBlock"] {
  box-sizing: border-box !important;
  width: 100% !important;
  height: 100% !important;
  min-height: 0 !important;
  max-height: 100% !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
  overscroll-behavior: contain !important;
  padding: 8px 4px 22px 0 !important;
  border-top: 1px solid rgba(49,88,113,.32);
}
.llm-zone-label {
  color: var(--gold);
  font-size: 11px;
  letter-spacing: .14em;
  font-weight: 800;
  margin: 2px 0 8px;
}
.llm-msg {
  margin: 18px 0;
  padding: 0;
  border-radius: 0;
  font-size: 15px;
  line-height: 1.8;
}
.llm-msg.user {
  margin-left: 64px;
  margin-right: 6px;
  padding: 12px 15px;
  border-radius: 18px 18px 4px 18px;
  color: var(--title);
  background: rgba(29,91,132,.34);
  border: 1px solid rgba(91,135,163,.44);
  width: fit-content;
  max-width: 82%;
  margin-left: auto;
}
.llm-msg.assistant {
  margin-right: 24px;
  color: var(--ice);
  background: transparent;
  border: none;
}
.llm-meta {
  color: var(--muted);
  font-size: 11px;
  margin: 14px 0 5px;
}
.llm-thinking {
  flex: 0 0 auto;
  margin: 8px 0 10px;
  padding: 7px 2px;
  border-radius: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.65;
  background: transparent;
  border: none;
}
.llm-thinking-dot {
  display:inline-block;
  width:7px;
  height:7px;
  border-radius:999px;
  background: var(--gold);
  margin-right:8px;
  box-shadow: 0 0 12px rgba(198,161,91,.5);
}
.llm-input-marker {
  height: 1px;
  flex: 0 0 auto;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"]:has(.llm-input-marker),
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"]:has(.llm-input-marker) {
  margin-top: 0 !important;
  flex: 0 0 auto !important;
}
.llm-composer-head {
  flex: 0 0 auto;
  display:flex;
  align-items:center;
  gap:10px;
  padding: 12px 14px 0;
  border: 1px solid rgba(91,135,163,.48);
  border-bottom: none;
  border-radius: 20px 20px 0 0;
  background: rgba(232,240,246,.055);
}
.llm-plus {
  color:#9fb2c3;
  font-size:24px;
  line-height:1;
}
.llm-context-pill,
.llm-model-pill {
  display:inline-flex;
  align-items:center;
  min-height:30px;
  padding:4px 11px;
  border-radius:10px;
  color:#dce8f0;
  background:rgba(8,27,43,.62);
  border:1px solid rgba(91,135,163,.42);
  font-size:13px;
}
.llm-model-pill {
  color:var(--muted);
  margin-left:auto;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stTextArea"] textarea {
  box-sizing: border-box !important;
  width: 100% !important;
  height: 136px !important;
  min-height: 136px !important;
  max-height: 136px !important;
  resize: none !important;
  overflow-y: auto !important;
  overscroll-behavior: contain !important;
  border-radius: 0 0 20px 20px !important;
  border: 1px solid rgba(91,135,163,.48) !important;
  border-top: none !important;
  background: rgba(232,240,246,.055) !important;
  color: var(--ice) !important;
  font-size: 15px !important;
  padding: 18px 16px !important;
  box-shadow: 0 16px 42px rgba(0,0,0,.18) !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stTextArea"],
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stTextArea"] > div,
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-baseweb="textarea"] {
  box-sizing: border-box !important;
  flex: 0 0 136px !important;
  width: 100% !important;
  height: 136px !important;
  min-height: 136px !important;
  max-height: 136px !important;
  overflow: hidden !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stTextArea"] textarea::placeholder {
  color: rgba(184,198,211,.72) !important;
}
div[data-testid="element-container"]:has(.llm-input-marker) ~ div[data-testid="element-container"]:has(textarea),
div[data-testid="stElementContainer"]:has(.llm-input-marker) ~ div[data-testid="stElementContainer"]:has(textarea) {
  margin-top: 0 !important;
  flex: 0 0 136px !important;
  height: 136px !important;
  min-height: 136px !important;
  max-height: 136px !important;
  overflow: hidden !important;
}
/* Native chat composer: reliable Enter submit, Shift+Enter newline, and zoom-safe docking. */
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stChatInput"] {
  position: relative !important;
  flex: 0 0 104px !important;
  width: 100% !important;
  height: 104px !important;
  min-height: 104px !important;
  max-height: 104px !important;
  margin: 0 !important;
  z-index: 15 !important;
  border: 1px solid rgba(91,135,163,.48) !important;
  border-top: none !important;
  border-radius: 0 0 20px 20px !important;
  background: rgba(232,240,246,.055) !important;
  box-shadow: 0 16px 42px rgba(0,0,0,.18) !important;
  overflow: hidden !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stChatInput"] textarea {
  box-sizing: border-box !important;
  width: 100% !important;
  height: 102px !important;
  min-height: 102px !important;
  max-height: 102px !important;
  resize: none !important;
  overflow-y: auto !important;
  overscroll-behavior: contain !important;
  padding: 18px 64px 18px 16px !important;
  color: var(--ice) !important;
  background: transparent !important;
  font-size: 15px !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stChatInput"] button {
  position: absolute !important;
  right: 13px !important;
  bottom: 13px !important;
  width: 44px !important;
  height: 44px !important;
  min-height: 44px !important;
  border-radius: 999px !important;
  color: #eef7ff !important;
  background: linear-gradient(135deg,#2c7cae,#1d5b84) !important;
  border: 1px solid rgba(125,183,221,.62) !important;
  box-shadow: 0 10px 24px rgba(0,0,0,.22) !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stChatInput"] textarea::placeholder {
  color: rgba(184,198,211,.72) !important;
}
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="element-container"]:has(div[data-testid="stChatInput"]),
div[data-testid="stColumn"]:has(.llm-chat-root) div[data-testid="stElementContainer"]:has(div[data-testid="stChatInput"]) {
  flex: 0 0 104px !important;
  height: 104px !important;
  min-height: 104px !important;
  max-height: 104px !important;
  overflow: visible !important;
}
@media (max-height: 700px) {
  .llm-header { padding-bottom: 6px; }
  .llm-title { font-size: 18px; margin-top: 0; }
  .llm-thinking { margin: 3px 0 5px; padding: 2px; }
  .llm-composer-head { padding-top: 7px; }
}
.main .block-container:has(.page-mode-history) { padding-top: 4.4rem; }
"""

SHARED_COMPONENTS = r"""
.stApp, [data-testid="stAppViewContainer"] > .main {
  color: var(--ice);
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}
.main .block-container { max-width: 1280px; padding-top: 4.4rem; padding-bottom: 4rem; }

h1, h2, h3, h4, p, li, label, [data-testid="stMarkdownContainer"] { color: var(--ice); }
h1, h2, h3 { font-family: "Noto Serif SC", Georgia, serif !important; }
a { color: var(--link) !important; }
hr { border-color: var(--line) !important; }

.brandline { display:flex; align-items:center; gap:10px; color:var(--ice); font-weight:700; letter-spacing:.04em; }
.brandmark { width:31px; height:31px; display:inline-grid; place-items:center; background:linear-gradient(145deg,#1c557d,#0d2d46); border:1px solid #376783; color:#fff; border-radius:7px; font-family:"Noto Serif SC",serif; }
.page-kicker { color:var(--gold); font-size:10px; letter-spacing:.2em; font-weight:700; }
.page-title { margin:6px 0 4px; font-family:"Noto Serif SC",Georgia,serif; font-size:30px; font-weight:600; color:var(--title); }
.page-subtitle { color:var(--muted); font-size:13px; margin-bottom:0; }

.hero-mini {
  border:1px solid var(--line); border-radius:14px; padding:16px 18px 14px;
  background: var(--card);
  box-shadow:0 14px 38px rgba(0,0,0,.18);
  margin-bottom:14px;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.history-hero-anchor),
[data-testid="stBorder"]:has(.history-hero-anchor) {
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  padding: 16px 18px 14px !important;
  background: var(--card) !important;
  box-shadow: 0 14px 38px rgba(0,0,0,.18) !important;
  margin-bottom: 14px !important;
}
.step-row { display:flex; flex-direction:column; gap:10px; margin:12px 0 4px; }
.step { border:1px solid var(--line); border-radius:10px; padding:10px 12px; background:var(--step); min-height:78px; }
.step.current { border-color: var(--gold); box-shadow: inset 0 0 0 1px rgba(198,161,91,.35); }
.step strong { display:block; color:var(--title); font-size:13px; margin-bottom:4px; }
.step-num { color:var(--gold); }
.step-desc, .step span { color:var(--muted); font-size:12px; line-height:1.55; }

.history-card {
  border: none; border-radius: 0; padding: 0; background: transparent; margin: 0;
}
.history-card .meta { color:var(--muted); font-size:12px; margin-top:4px; }

.pick-card-anchor, .history-card-anchor, .history-hero-anchor, .title-new, .topbar-dots { display: none !important; }

[data-testid="stVerticalBlockBorderWrapper"]:has(.pick-card-anchor),
[data-testid="stVerticalBlockBorderWrapper"]:has(.history-card-anchor),
[data-testid="stBorder"]:has(.pick-card-anchor),
[data-testid="stBorder"]:has(.history-card-anchor) {
  border: 1px solid var(--line) !important;
  border-left: 3px solid #5b87a3 !important;
  border-radius: 12px !important;
  background: var(--step) !important;
  padding: 10px 12px 8px !important;
  margin-bottom: 12px !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.pick-card-anchor.selected),
[data-testid="stVerticalBlockBorderWrapper"]:has(.history-card-anchor),
[data-testid="stBorder"]:has(.pick-card-anchor.selected),
[data-testid="stBorder"]:has(.history-card-anchor) {
  background: var(--step) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.pick-card-anchor.selected),
[data-testid="stBorder"]:has(.pick-card-anchor.selected) {
  border-left-color: var(--gold) !important;
}
.pick-title {
  margin: 2px 0 8px;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif !important;
  font-size: 16px;
  font-weight: 700;
  color: var(--title);
  line-height: 1.35;
}
.pick-card {
  border: none;
  padding: 0;
  background: transparent;
  margin: 0;
}
.pick-card.selected { box-shadow: none; }
.pick-tags { display:flex; flex-wrap:wrap; gap:6px; margin: 0 0 10px; }
.pick-tag {
  display:inline-block; padding:2px 8px; border-radius:6px;
  font-size:11px; color:var(--muted); background:rgba(125,183,221,.10);
  border:1px solid var(--line);
}
.pick-tag.priority {
  border-radius:999px; color:#e0a45a; border-color:#c48a3e; background:transparent;
}
.pick-tag.risk-pass { border-radius:999px; color:#7dcea0; border-color:#2d6a4f; background:transparent; }
.pick-tag.risk-kill { border-radius:999px; color:#e07a5f; border-color:#c5281c; background:transparent; }
.pick-tag.risk-gap { border-radius:999px; color:#e0a45a; border-color:#c48a3e; background:transparent; }
.pick-row { border-top:1px solid var(--line); padding:10px 0 2px; }
.pick-row:first-of-type { border-top:none; padding-top:2px; }
.pick-label { font-weight:700; font-size:13px; color:var(--title); }
.pick-body { color:var(--muted); font-size:13px; line-height:1.7; margin-top:6px; white-space:pre-wrap; }
.pick-body.substance { white-space:normal; line-height:1.75; }
.pick-dupont { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:8px; }
.pick-dupont-item {
  padding:8px 8px 7px; border-radius:8px; background:rgba(125,183,221,.08);
  border:1px solid var(--line);
}
.pick-dupont-item .k { display:block; font-size:11px; color:var(--muted); }
.pick-dupont-item .v { display:block; margin-top:3px; font-size:15px; font-weight:750; color:var(--title); font-variant-numeric:tabular-nums; }
.pick-dupont-item.from-source { border-color:#c48a3e; background:rgba(196,138,62,.10); }
.pick-dupont-item.from-source .v { color:#e0a45a; }
.pick-dupont-note { margin-top:6px; font-size:11px; color:var(--muted); }

div[data-testid="stCheckbox"] { padding-top: 4px; }

.billing-panel { margin:1rem 0 1.25rem; padding:1.2rem; border-radius:16px; background:linear-gradient(135deg,#071f33,#123f5a); color:white; border:1px solid var(--line); }
.billing-title { font-size:1.05rem; font-weight:700; margin-bottom:.85rem; }
.billing-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.75rem; }
.billing-card { padding:.85rem .95rem; border-radius:12px; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.12); }
.billing-card.primary { background:rgba(198,161,91,.14); border-color:rgba(198,161,91,.38); }
.billing-label { font-size:.82rem; opacity:.78; margin-bottom:.2rem; }
.billing-value { font-size:1.55rem; line-height:1.1; font-weight:800; font-variant-numeric:tabular-nums; }
.billing-note { font-size:.74rem; opacity:.68; margin-top:.25rem; }

[data-testid="stMetric"] { background:var(--step); border:1px solid var(--line); border-radius:10px; padding:13px 15px; }
[data-testid="stFileUploaderDropzone"], [data-baseweb="input"] > div, [data-baseweb="textarea"] > div, [data-baseweb="select"] > div {
  background: var(--input) !important; border-color: var(--line) !important; color: var(--ice) !important;
}
[data-testid="stExpander"] { border-color:var(--line); background:var(--step); }
[data-testid="stDataFrame"] { background:var(--step); }
input[type="password"] { user-select:none; -webkit-user-select:none; }

.stButton > button, .stFormSubmitButton > button { border-radius:7px; min-height:40px; font-weight:650; color:var(--ice); background:var(--input); border-color:var(--line); }
.stButton > button:hover, .stFormSubmitButton > button:hover { color:var(--title); border-color:#5b87a3; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background:linear-gradient(135deg,#1d5b84,#123c5c); border-color:#3c789d; color:white; }

@media (max-width:800px) {
  .billing-grid { grid-template-columns:1fr; }
  .pick-dupont { grid-template-columns:1fr; }
  .app-topbar { padding-right: 110px; }
  .app-topbar-account { display:none; }
  .top-stagebar { left: 43%; }
  .top-stage { padding: 0 6px; }
  .top-stage-label { display:none; }
  .top-stage-connector { width: 10px; margin: 0 3px; }
  [data-testid="stMainBlockContainer"]:has(.page-mode-research),
  .main .block-container:has(.page-mode-research) { padding-left: 18px; padding-right: 18px; }
  .main .block-container:has(.llm-drawer-state.is-open) { padding-right: 1rem; }
  div[data-testid="element-container"]:has(.llm-drawer-state) + div[data-testid="element-container"],
  div[data-testid="stElementContainer"]:has(.llm-drawer-state) + div[data-testid="stElementContainer"] {
    top: auto !important;
    bottom: 20px !important;
    right: 0 !important;
    transform: none !important;
  }
  div[data-testid="element-container"]:has(.llm-drawer-anchor) + div[data-testid="element-container"],
  div[data-testid="stElementContainer"]:has(.llm-drawer-anchor) + div[data-testid="stElementContainer"] {
    position: relative !important;
    top: auto !important;
    right: auto !important;
    bottom: auto !important;
    width: auto !important;
    margin: 1rem 0 !important;
    transform: none !important;
  }
}
"""

DARK_VARS = r"""
:root {
  --navy-950: #061522;
  --ice: #e8f0f6;
  --title: #f1f6fa;
  --muted: #91a6b8;
  --line: #21445f;
  --gold: #c6a15b;
  --link: #7db7dd;
  --card: linear-gradient(145deg,rgba(15,43,65,.96),rgba(9,29,46,.96));
  --step: rgba(6,21,34,.44);
  --input: #0b2438;
}
.stApp, [data-testid="stAppViewContainer"] > .main {
  background: radial-gradient(circle at 78% -15%, #153f5f 0, #091d2e 38%, #061522 100%);
}
"""

LIGHT_VARS = r"""
:root {
  --navy-950: #f4efe4;
  --ice: #1b3346;
  --title: #102738;
  --muted: #5d7386;
  --line: #cfc3aa;
  --gold: #9a7a3a;
  --link: #1d5b84;
  --card: linear-gradient(145deg,rgba(255,252,246,.96),rgba(244,239,228,.94));
  --step: rgba(255,255,255,.62);
  --input: #fffdf8;
}
.stApp, [data-testid="stAppViewContainer"] > .main {
  background: radial-gradient(circle at 12% -10%, #fffaf0 0, #f4efe4 42%, #ebe3d3 100%);
}
"""

FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;600&family=Inter:wght@400;500;600;700&display=swap');\n"

LOGIN_CSS = r"""
<style>
""" + FONT_IMPORT + CHROME_CSS + r"""
.stApp, [data-testid="stAppViewContainer"] > .main {
  color: #e8f0f6;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
  background-color: #061522;
  background-image: linear-gradient(90deg, #132c3b 0 19%, #091c29 19% 81%, #294542 81% 100%);
  background-size: cover;
}

.main .block-container { max-width: 1280px; padding-top: 9vh; padding-bottom: 4rem; }
h1, h2, h3, p, li, label, [data-testid="stMarkdownContainer"] { color: #e8f0f6; }
h1, h2, h3 { font-family: "Noto Serif SC", Georgia, serif !important; }

.page-kicker { color:#c6a15b; font-size:10px; letter-spacing:.2em; font-weight:700; }
.page-title { margin:8px 0 6px; font-family:"Noto Serif SC",Georgia,serif; font-size:28px; font-weight:600; color:#f1f6fa; }
.page-subtitle { color:#91a6b8; font-size:13px; margin-bottom:0; line-height:1.6; }

.hero-mini {
  border:1px solid #21445f; border-radius:14px; padding:18px 18px 16px;
  background: #122c3d;
  box-shadow:0 18px 48px rgba(0,0,0,.28);
  margin-bottom:12px;
  backdrop-filter: blur(10px);
}

[data-testid="stFileUploaderDropzone"], [data-baseweb="input"] > div, [data-baseweb="textarea"] > div {
  background:#0b2438 !important; border-color:#2a506b !important; color:#e7f0f6 !important;
}
input[type="password"] { user-select:none; -webkit-user-select:none; }
.stButton > button, .stFormSubmitButton > button { border-radius:7px; min-height:40px; font-weight:650; }
.stFormSubmitButton > button[kind="primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background:#c6ae7d; border-color:#c6ae7d; color:#102633; font-weight:650;
}
</style>
"""

# Compact horizontal cover; scoped to the signed-out page.
LOGIN_CSS += r"""<style>
[data-testid="stMainBlockContainer"], .main .block-container {
  max-width:1120px; padding:clamp(80px,17vh,170px) 40px 60px;
}
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .login-shell-anchor) {
  padding:40px 44px; border:1px solid rgba(198,174,125,.3); border-radius:18px;
  background:linear-gradient(110deg,rgba(8,25,38,.32),rgba(13,34,48,.22));
  box-shadow:0 28px 90px rgba(0,0,0,.22); backdrop-filter:blur(2px);
}
.login-shell-anchor {display:none;}
.hero-mini {border:0; border-radius:0; padding:20px 12px 0 0; margin:0; background:none; box-shadow:none; backdrop-filter:none;}
.page-kicker {letter-spacing:.18em; font-size:10px; color:#cdbb94;}
.page-title {font-size:clamp(28px,3.1vw,43px); line-height:1.18; max-width:590px; margin:22px 0; text-wrap:balance;}
.cover-rule {width:54px;height:2px;background:#c6ae7d;margin:26px 0;}
.page-subtitle {font-size:15px;line-height:1.7;color:#c4d1da;max-width:400px;}
.cover-workflow {font-size:11px;letter-spacing:.045em;color:#8fa6b7;margin-top:28px;}
[data-testid="stForm"] {border:0;padding:0;background:transparent;}
[data-testid="stBaseButton-primaryFormSubmit"] {background:#c6ae7d !important;color:#102633 !important;border-color:#c6ae7d !important;}
[data-testid="stBaseButton-primaryFormSubmit"] p {color:#102633 !important;}
@media(max-width:760px) {
 [data-testid="stMainBlockContainer"], .main .block-container {padding:48px 20px;}
 [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .login-shell-anchor) {padding:26px 24px;}
 .hero-mini {padding:0 0 12px;}
 .page-title {font-size:30px; margin:16px 0;}
 .cover-rule {margin:18px 0;} .cover-workflow {margin-top:16px;}
}
</style>"""


APP_CSS = f"<style>\n{FONT_IMPORT}\n{CHROME_CSS}\n{DARK_VARS}\n{SHARED_COMPONENTS}\n{TOPBAR_CSS}\n</style>"

WORKSPACE_CSS = r"""
@media(min-width:900px) {
 [data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] .research-cards-anchor) {
   position:sticky; top:106px; align-self:flex-start;
 }
 .st-key-research_cards_scroll,
 [data-testid="stLayoutWrapper"]:has(> .st-key-research_cards_scroll) {
   height:min(760px, calc(100dvh - 140px)) !important;
   max-height:calc(100dvh - 140px) !important;
   min-height:0 !important;
 }
 .st-key-research_cards_scroll {overflow-y:auto !important;}
}
[data-testid="stColumn"]:has(.research-cards-anchor) .pick-body {font-size:13px;}
[data-testid="stColumn"]:has(.research-reports-anchor) [data-testid="stMarkdownContainer"] table {
 font-size:13px;
}
[data-testid="stColumn"]:has(.research-reports-anchor) h1 {font-size:28px;}
[data-testid="stColumn"]:has(.research-reports-anchor) h2 {font-size:22px;}
[data-testid="stColumn"]:has(.research-reports-anchor) h3 {font-size:18px;}
"""


def _page_background_css(theme: str, background_path: Path | None) -> str:
    if not background_path or not background_path.is_file():
        return ""
    if background_path.parent.name == "static":
        image_url = f"app/static/{background_path.name}"
    else:
        encoded = base64.b64encode(background_path.read_bytes()).decode("ascii")
        mime = "image/webp" if background_path.suffix.lower() == ".webp" else "image/jpeg"
        image_url = f"data:{mime};base64,{encoded}"
    is_light = str(theme).strip().lower() == "light"
    overlay = (
        "linear-gradient(rgba(244,239,228,.80), rgba(235,227,211,.88))"
        if is_light
        else "linear-gradient(rgba(3,17,28,.40), rgba(3,17,28,.68))"
    )
    return f"""
.stApp, [data-testid="stAppViewContainer"] > .main {{
  background-color: {'#ebe3d3' if is_light else '#061522'};
  background-image: {overlay}, url("{image_url}");
  background-size: cover;
  background-position: center center;
  background-repeat: no-repeat;
  background-attachment: fixed;
}}
"""


def css_for_theme(theme: str, background_path: Path | None = None) -> str:
    palette = LIGHT_VARS if str(theme).strip().lower() == "light" else DARK_VARS
    background = _page_background_css(theme, background_path)
    return f"<style>\n{FONT_IMPORT}\n{CHROME_CSS}\n{palette}\n{SHARED_COMPONENTS}\n{TOPBAR_CSS}\n{WORKSPACE_CSS}\n{background}\n</style>"


def login_css(background_path: Path | None = None) -> str:
    background = _page_background_css("Dark", background_path)
    return LOGIN_CSS + (f"<style>\n{background}\n</style>" if background else "")
