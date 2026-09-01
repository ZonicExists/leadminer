"""
Interactive Web UI Dashboard for Google Maps Lead Generation Scraper (Streamlit).
Minimalistic dark aesthetic with typography, micro-animations, 3D interactive tilt cards,
ambient floating orbs, quick-start chips, and live lead pipeline.
"""
import asyncio
import io
import os
import time
import threading
from queue import Queue, Empty
from typing import List, Optional

import pandas as pd
import streamlit as st

from src.models import BusinessLead
from src.enricher import WebsiteEnricher
from src.exporter import export_leads
from src.scraper_pool import ScraperPool, WorkerResult
from src.utils import (
    deduplicate_leads,
    load_proxies_from_file,
    filter_leads,
    load_saved_proxy_config,
    save_proxy_config,
    load_saved_sidebar_config,
    save_sidebar_config,
    save_session_checkpoint,
    load_session_checkpoint,
    clear_session_checkpoint,
    parse_proxy_string,
)
from src.geo_expander import generate_sub_queries
from src.ai_processor import OllamaClient, DEFAULT_OLLAMA_ENDPOINT, DEFAULT_OLLAMA_MODEL

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LeadMiner — Google Maps B2B Lead Intelligence",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Global Styles + 3D Animations ─────────────────────────────────────────────
def inject_styles():
    st.markdown("""
<style>
/* ── Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ── Base ── */
*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    background-color: #07070b !important;
    color: #e2e8f0;
}

/* ── Subtle Dot Grid Background ── */
.stApp {
    background-color: #07070b !important;
    background-image: radial-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px) !important;
    background-size: 28px 28px !important;
}

/* ── Ambient Glowing Orbs ── */
.ambient-glow-1 {
    position: fixed;
    top: -120px;
    right: 5%;
    width: 550px;
    height: 550px;
    background: radial-gradient(circle, rgba(99, 102, 241, 0.12) 0%, rgba(139, 92, 246, 0.04) 45%, transparent 70%);
    filter: blur(60px);
    pointer-events: none;
    z-index: 0;
    animation: orbFloat1 18s ease-in-out infinite alternate;
}
.ambient-glow-2 {
    position: fixed;
    top: 40%;
    left: -100px;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(56, 189, 248, 0.08) 0%, rgba(99, 102, 241, 0.03) 50%, transparent 70%);
    filter: blur(70px);
    pointer-events: none;
    z-index: 0;
    animation: orbFloat2 22s ease-in-out infinite alternate;
}
@keyframes orbFloat1 {
    0%   { transform: translate(0, 0) scale(1); }
    100% { transform: translate(-60px, 80px) scale(1.15); }
}
@keyframes orbFloat2 {
    0%   { transform: translate(0, 0) scale(1); }
    100% { transform: translate(70px, -60px) scale(1.1); }
}

/* ── Clean Up Streamlit Clutter without hiding sidebar controls ── */
#MainMenu, footer { visibility: hidden; }
.stDeployButton, [data-testid="stBaseButton-header"] { display: none !important; }
[data-testid="stToolbarActions"] { display: none !important; }
[data-testid="stHeaderActionElements"],
.header-anchor,
a[href*="#"] svg,
h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {
    display: none !important;
}

/* Header styling: transparent, but leaves the sidebar expand button accessible */
header[data-testid="stHeader"] {
    background: transparent !important;
    height: 3.2rem !important;
    z-index: 999 !important;
}

/* ── Always Visible & Glowing Sidebar Toggle Controls ── */
button[data-testid="stExpandSidebarButton"],
[data-testid="stSidebarCollapsedControl"],
button[aria-label*="sidebar" i] {
    visibility: visible !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background: rgba(13, 13, 22, 0.95) !important;
    border: 1px solid rgba(99, 102, 241, 0.5) !important;
    border-radius: 10px !important;
    color: #818cf8 !important;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5), 0 0 12px rgba(99, 102, 241, 0.3) !important;
    cursor: pointer !important;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
    z-index: 1000 !important;
}
button[data-testid="stExpandSidebarButton"]:hover,
[data-testid="stSidebarCollapsedControl"]:hover {
    background: #6366f1 !important;
    color: #ffffff !important;
    border-color: #818cf8 !important;
    transform: scale(1.08) !important;
    box-shadow: 0 6px 22px rgba(99, 102, 241, 0.6) !important;
}
button[data-testid="stSidebarCollapseButton"] {
    color: #94a3b8 !important;
    transition: all 0.2s ease !important;
}
button[data-testid="stSidebarCollapseButton"]:hover {
    color: #818cf8 !important;
    transform: scale(1.05) !important;
}

/* ── Layout Container ── */
.block-container {
    padding: 2rem 3rem 4rem !important;
    max-width: 1360px !important;
    position: relative;
    z-index: 1;
}

/* ── Custom Sleek Scrollbar ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #6366f1; }

/* ── Sidebar Styling ── */
[data-testid="stSidebar"] {
    background-color: #07070e !important;
    border-right: 1px solid rgba(255, 255, 255, 0.07) !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 1rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}

/* Sidebar Section Cards */
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(13, 13, 24, 0.75) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255, 255, 255, 0.07) !important;
    border-radius: 16px !important;
    padding: 0.85rem 0.95rem !important;
    margin-bottom: 0.65rem !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35) !important;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: rgba(99, 102, 241, 0.4) !important;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.5), 0 0 16px rgba(99, 102, 241, 0.15) !important;
    transform: translateY(-1px) !important;
}

/* Sidebar Segmented Control */
[data-testid="stSidebar"] [data-testid="stSegmentedControl"] {
    background: rgba(8, 8, 16, 0.85) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px !important;
    padding: 3px !important;
    gap: 3px !important;
}
[data-testid="stSidebar"] [data-testid="stSegmentedControl"] button {
    border-radius: 7px !important;
    font-size: 0.74rem !important;
    font-weight: 500 !important;
    color: #94a3b8 !important;
    padding: 0.35rem 0.6rem !important;
    transition: all 0.18s ease !important;
}
[data-testid="stSidebar"] [data-testid="stSegmentedControl"] button[aria-checked="true"] {
    background: linear-gradient(135deg, #6366f1, #7c3aed) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 8px rgba(99, 102, 241, 0.45) !important;
}

/* Sidebar Toggle Switches */
[data-testid="stSidebar"] [data-testid="stToggle"] {
    margin-bottom: 0.3rem !important;
    padding: 0.15rem 0 !important;
}
[data-testid="stSidebar"] [data-testid="stToggle"] label p {
    font-size: 0.82rem !important;
    color: #e2e8f0 !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] [data-testid="stToggle"] input:checked ~ div {
    background-color: #6366f1 !important;
    box-shadow: 0 0 10px rgba(99, 102, 241, 0.6) !important;
}

/* Sidebar Sliders */
[data-testid="stSidebar"] [data-testid="stSlider"] label p {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    color: #64748b !important;
}

/* ── Bordered Container (Glassmorphic Console Box) ── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(13, 13, 22, 0.65) !important;
    backdrop-filter: blur(24px) !important;
    -webkit-backdrop-filter: blur(24px) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 20px !important;
    padding: 0.8rem 1rem !important;
    box-shadow: 0 20px 48px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
}

/* ── Inputs & Text Areas ── */
.stTextInput input, .stTextArea textarea {
    background: rgba(15, 15, 26, 0.8) !important;
    border: 1px solid rgba(255, 255, 255, 0.09) !important;
    border-radius: 12px !important;
    color: #f8fafc !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.92rem !important;
    padding: 0.75rem 1rem !important;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.4) !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2), inset 0 2px 4px rgba(0, 0, 0, 0.4) !important;
    background: rgba(20, 20, 36, 0.95) !important;
    outline: none !important;
}

/* ── Tabs (React-Aria & BaseWeb fixes) ── */
.react-aria-SelectionIndicator,
[class*="SelectionIndicator"],
div[data-testid="stTabs"] [class*="SelectionIndicator"],
div[data-baseweb="tab-highlight"] {
    background: linear-gradient(90deg, #6366f1, #a855f7) !important;
    background-color: #6366f1 !important;
    box-shadow: 0 0 12px rgba(99, 102, 241, 0.8) !important;
    height: 3px !important;
    border-radius: 3px 3px 0 0 !important;
}
div[data-testid="stTabs"] [aria-selected="true"] p,
div[data-testid="stTabs"] [aria-selected="true"] div,
div[data-testid="stTabs"] [aria-selected="true"] {
    color: #818cf8 !important;
    font-weight: 600 !important;
}
button[data-baseweb="tab"] {
    background: transparent !important;
    border: none !important;
    color: #64748b !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    padding: 0.65rem 1.1rem !important;
    transition: color 0.2s ease, transform 0.15s ease !important;
}
button[data-baseweb="tab"]:hover {
    color: #cbd5e1 !important;
    transform: translateY(-1px) !important;
}

/* ── Primary Button with Shimmer Sweep ── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #6366f1 100%) !important;
    background-size: 200% auto !important;
    color: #ffffff !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
    border-radius: 12px !important;
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    padding: 0.75rem 2rem !important;
    letter-spacing: 0.02em !important;
    box-shadow: 0 6px 24px rgba(99, 102, 241, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.25) !important;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
    position: relative !important;
    overflow: hidden !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px) scale(1.01) !important;
    box-shadow: 0 10px 32px rgba(99, 102, 241, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.35) !important;
    background-position: right center !important;
}
.stButton > button[kind="primary"]:active {
    transform: translateY(0) scale(0.99) !important;
}

/* ── Secondary Buttons (Quick Fill Chips) ── */
.stButton > button:not([kind="primary"]) {
    background: rgba(18, 18, 30, 0.8) !important;
    color: #94a3b8 !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 10px !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    padding: 0.45rem 0.85rem !important;
    transition: all 0.2s ease !important;
}
.stButton > button:not([kind="primary"]):hover {
    border-color: rgba(99, 102, 241, 0.6) !important;
    color: #f8fafc !important;
    background: rgba(30, 30, 50, 0.9) !important;
    transform: translateY(-1px) !important;
}

/* ── Download Buttons ── */
.stDownloadButton > button {
    background: rgba(18, 18, 32, 0.9) !important;
    color: #818cf8 !important;
    border: 1px solid rgba(99, 102, 241, 0.4) !important;
    border-radius: 10px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.2rem !important;
    transition: all 0.2s ease !important;
}
.stDownloadButton > button:hover {
    background: #6366f1 !important;
    color: #ffffff !important;
    border-color: #6366f1 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45) !important;
}

/* ── Sliders & Controls Accent ── */
[class*="stSlider"] div[role="slider"],
[data-testid="stSlider"] [role="slider"] {
    background: #6366f1 !important;
    background-color: #6366f1 !important;
    box-shadow: 0 0 12px rgba(99, 102, 241, 0.8) !important;
    width: 14px !important;
    height: 14px !important;
    transition: transform 0.15s ease !important;
}
[class*="stSlider"] div[role="slider"]:hover {
    transform: scale(1.3) !important;
}
[class*="stSlider"] div[data-testid="stThumbValue"] {
    color: #818cf8 !important;
}

/* ── Dataframe Styling ── */
[data-testid="stDataFrame"] > div {
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 14px !important;
    background: #090910 !important;
}

/* ── Hero Component Styles ── */
.hero-container {
    margin-bottom: 1.5rem;
    position: relative;
    animation: fadeIn 0.6s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: translateY(0); }
}

.hero-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #818cf8;
    margin-bottom: 0.5rem;
}
.hero-tag-dot {
    width: 6px;
    height: 6px;
    background: #6366f1;
    border-radius: 50%;
    box-shadow: 0 0 8px #6366f1;
}

.hero-title {
    font-size: clamp(2rem, 3.2vw, 2.6rem);
    font-weight: 800;
    letter-spacing: -0.035em;
    line-height: 1.1;
    margin: 0 0 0.6rem 0;
    background: linear-gradient(135deg, #ffffff 30%, #cbd5e1 70%, #818cf8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero-title span {
    background: linear-gradient(135deg, #818cf8 0%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.hero-desc {
    font-size: 0.92rem;
    color: #64748b;
    max-width: 600px;
    line-height: 1.6;
    margin: 0 0 1rem 0;
}

.hero-pill-row {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    flex-wrap: wrap;
}
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    background: rgba(16, 185, 129, 0.08);
    border: 1px solid rgba(16, 185, 129, 0.22);
    border-radius: 100px;
    padding: 0.28rem 0.8rem;
    font-size: 0.72rem;
    font-weight: 500;
    color: #10b981;
}
.status-pill-dot {
    width: 6px;
    height: 6px;
    background: #10b981;
    border-radius: 50%;
    box-shadow: 0 0 8px #10b981;
    animation: pulseDot 2s ease-in-out infinite;
}
@keyframes pulseDot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.4; transform: scale(0.85); }
}

.feature-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 100px;
    padding: 0.28rem 0.75rem;
    font-size: 0.72rem;
    color: #94a3b8;
}

/* ── Interactive 3D Bento Grid ── */
.bento-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1.1rem;
    margin-top: 0.8rem;
    margin-bottom: 2rem;
}
@media (max-width: 1024px) {
    .bento-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
    .bento-grid { grid-template-columns: 1fr; }
}

.bento-card {
    background: rgba(13, 13, 22, 0.65);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 16px;
    padding: 1.3rem 1.3rem;
    position: relative;
    overflow: hidden;
    cursor: default;
    transform-style: preserve-3d;
    transition: border-color 0.3s ease, box-shadow 0.3s ease, transform 0.15s ease-out;
    will-change: transform;
}
.bento-card:hover {
    border-color: rgba(99, 102, 241, 0.45);
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5), 0 0 20px rgba(99, 102, 241, 0.15);
}
.bento-card-sheen {
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.07) 0%, transparent 60%);
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.3s ease;
    border-radius: inherit;
}
.bento-card:hover .bento-card-sheen {
    opacity: 1;
}
.bento-icon {
    font-size: 1.4rem;
    margin-bottom: 0.7rem;
    display: inline-block;
}
.bento-tag {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #818cf8;
    margin-bottom: 0.3rem;
}
.bento-heading {
    font-size: 0.96rem;
    font-weight: 700;
    color: #f1f5f9;
    margin: 0 0 0.35rem;
}
.bento-desc {
    font-size: 0.78rem;
    color: #64748b;
    line-height: 1.5;
    margin: 0;
}
.bento-footer {
    margin-top: 0.9rem;
    padding-top: 0.7rem;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.bento-stat {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    color: #cbd5e1;
}
.bento-badge {
    font-size: 0.65rem;
    padding: 2px 7px;
    border-radius: 6px;
    background: rgba(99, 102, 241, 0.15);
    color: #818cf8;
    font-weight: 600;
}

/* ── Section Dividers ── */
.section-bar {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin: 1.6rem 0 0.9rem;
}
.section-bar-title {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #475569;
    white-space: nowrap;
}
.section-bar-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(255, 255, 255, 0.08) 0%, transparent 100%);
}

/* ── Result Stat Cards ── */
.stat-card-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 0.8rem;
    margin-top: 1rem;
    margin-bottom: 1.5rem;
}
@media (max-width: 1024px) {
    .stat-card-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 640px) {
    .stat-card-grid { grid-template-columns: repeat(2, 1fr); }
}

.stat-box {
    background: rgba(13, 13, 22, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 1.1rem 1.2rem;
    position: relative;
    overflow: hidden;
    transform-style: preserve-3d;
    transition: all 0.25s ease;
}
.stat-box:hover {
    border-color: rgba(99, 102, 241, 0.5);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
.stat-box-label {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 0.35rem;
}
.stat-box-num {
    font-size: 1.7rem;
    font-weight: 800;
    color: #f8fafc;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}
.stat-box-num.accent { color: #818cf8; }
.stat-box-num.green  { color: #10b981; }
.stat-box-num.amber  { color: #f59e0b; }
</style>

<!-- Ambient Glow Elements -->
<div class="ambient-glow-1"></div>
<div class="ambient-glow-2"></div>

<script>
// ── Real-time 3D Card Tilt with Mouse Tracking ────────────────────────────────
(function() {
    function init3DTilt() {
        const cards = document.querySelectorAll('.bento-card, .stat-box');
        cards.forEach(card => {
            if (card.dataset.tiltInit) return;
            card.dataset.tiltInit = 'true';

            card.addEventListener('mousemove', e => {
                const rect = card.getBoundingClientRect();
                const x = (e.clientX - rect.left) / rect.width  - 0.5;
                const y = (e.clientY - rect.top)  / rect.height - 0.5;

                // Subtle smooth 3D tilt
                const rotX = -y * 12;
                const rotY = x * 12;
                card.style.transform = `perspective(700px) rotateX(${rotX}deg) rotateY(${rotY}deg) scale3d(1.02, 1.02, 1.02)`;

                // Dynamic sheen highlight following mouse
                const sheen = card.querySelector('.bento-card-sheen');
                if (sheen) {
                    const posX = (e.clientX - rect.left) / rect.width * 100;
                    const posY = (e.clientY - rect.top) / rect.height * 100;
                    sheen.style.background = `radial-gradient(circle at ${posX}% ${posY}%, rgba(255,255,255,0.12) 0%, transparent 65%)`;
                }
            });

            card.addEventListener('mouseleave', () => {
                card.style.transform = 'perspective(700px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
            });
        });
    // ── Auto-Expand Sidebar on Load if Collapsed ────────────────────────────────
    function autoExpandSidebar() {
        const expandBtn = document.querySelector('[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"], button[aria-label*="sidebar" i]');
        if (expandBtn && window.getComputedStyle(expandBtn).display !== 'none') {
            expandBtn.click();
        }
    }

    const observer = new MutationObserver(() => {
        init3DTilt();
        autoExpandSidebar();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    init3DTilt();
    setTimeout(autoExpandSidebar, 200);
    setTimeout(autoExpandSidebar, 600);
    setTimeout(autoExpandSidebar, 1200);
})();
</script>
""", unsafe_allow_html=True)


# ── Section Divider Component ──────────────────────────────────────────────────
def section_header(title: str):
    st.markdown(f"""
<div class="section-bar">
  <span class="section-bar-title">{title}</span>
  <div class="section-bar-line"></div>
</div>
""", unsafe_allow_html=True)


# ── Parse Proxy List Helper ────────────────────────────────────────────────────
def parse_proxy_list(text: str) -> List[str]:
    lines = []
    for line in text.replace(",", "\n").split("\n"):
        clean = line.strip()
        if clean and not clean.startswith("#"):
            lines.append(clean)
    return lines


# ── Thread Runner for Scraper Pool ─────────────────────────────────────────────
def run_pool_in_thread(
    queries: List[str],
    limit: int,
    threads: int,
    headless: bool,
    delay: float,
    proxies: List[str],
    enable_solver: bool,
    solver_ext: str,
    lead_queue: Queue,
    result_queue: Queue,
    stop_event: Optional[threading.Event] = None,
    initial_leads: Optional[List[BusinessLead]] = None,
    all_target_queries: Optional[List[str]] = None,
    checkpoint_config: Optional[Dict[str, Any]] = None,
):
    async def _run():
        try:
            all_leads: List[BusinessLead] = list(initial_leads or [])
            all_queries = list(all_target_queries or queries)
            completed_queries: List[str] = [q for q in all_queries if q not in queries]

            def on_lead(lead: BusinessLead, worker_id: int):
                all_leads.append(lead)
                lead_queue.put(("lead", worker_id, lead))
                # Periodic or per-lead checkpoint
                pending = [q for q in all_queries if q not in completed_queries]
                status_str = "paused" if (stop_event and stop_event.is_set()) else "running"
                save_session_checkpoint(
                    status=status_str,
                    queries=all_queries,
                    completed_queries=completed_queries,
                    pending_queries=pending,
                    leads=all_leads,
                    config=checkpoint_config,
                )

            def on_worker_done(result: WorkerResult):
                if not result.error or "timeout" in (result.error or "").lower():
                    if result.query not in completed_queries:
                        completed_queries.append(result.query)
                lead_queue.put(("worker_done", result.worker_id, result))
                pending = [q for q in all_queries if q not in completed_queries]
                status_str = "paused" if (stop_event and stop_event.is_set()) else "running"
                save_session_checkpoint(
                    status=status_str,
                    queries=all_queries,
                    completed_queries=completed_queries,
                    pending_queries=pending,
                    leads=all_leads,
                    config=checkpoint_config,
                )

            pool = ScraperPool(
                threads=threads,
                headless=headless,
                delay=delay,
                proxies=proxies if proxies else None,
                enable_captcha_solver=enable_solver,
                solver_ext=solver_ext,
                lead_callback=on_lead,
                worker_callback=on_worker_done,
                stop_event=stop_event,
            )
            worker_results = await pool.run(queries=queries, limit_per_query=limit)
            unique = deduplicate_leads(all_leads + pool.get_all_leads(deduplicate=False))

            pending_final = [q for q in all_queries if q not in completed_queries]
            if stop_event and stop_event.is_set():
                save_session_checkpoint(
                    status="paused",
                    queries=all_queries,
                    completed_queries=completed_queries,
                    pending_queries=pending_final,
                    leads=unique,
                    config=checkpoint_config,
                )
                result_queue.put(("paused", unique, worker_results))
            else:
                save_session_checkpoint(
                    status="completed",
                    queries=all_queries,
                    completed_queries=completed_queries,
                    pending_queries=[],
                    leads=unique,
                    config=checkpoint_config,
                )
                result_queue.put(("done", unique, worker_results))

        except Exception as exc:
            import traceback
            traceback.print_exc()
            result_queue.put(("error", [], str(exc)))

    try:
        asyncio.run(_run())
    except Exception as exc:
        result_queue.put(("error", [], str(exc)))


# ── Main Application UI ────────────────────────────────────────────────────────
def main():
    inject_styles()

    # ── Hero Section (No markdown header anchors!) ────────────────────────────
    st.markdown("""
<div class="hero-container">
  <div class="hero-tag">
    <div class="hero-tag-dot"></div>
    B2B Intelligence & Prospecting Engine
  </div>
  <div class="hero-title">Lead<span>Miner</span></div>
  <p class="hero-desc">
    Target high-value prospects without a website, verified decision-maker emails,
    phone numbers, and social channels — powered by concurrent browser workers.
  </p>
  <div class="hero-pill-row">
    <div class="status-pill">
      <div class="status-pill-dot"></div>
      Cluster Ready
    </div>
    <div class="feature-pill">⚡ Multi-Thread Pool</div>
    <div class="feature-pill">🛡️ Bit Solver Active</div>
    <div class="feature-pill">🎯 Web Builder Filter Mode</div>
    <div class="feature-pill">🌍 90+ Countries</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        # Cluster Brand Header
        st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;padding:0.2rem 0 0.8rem;border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:0.8rem;">
  <div style="display:flex;align-items:center;gap:0.55rem;">
    <div style="width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg, rgba(99,102,241,0.25), rgba(139,92,246,0.15));border:1px solid rgba(99,102,241,0.4);display:flex;align-items:center;justify-content:center;font-size:0.9rem;color:#818cf8;">⬡</div>
    <div>
      <div style="font-size:0.88rem;font-weight:700;color:#f8fafc;letter-spacing:-0.01em;line-height:1.2;">Cluster Config</div>
      <div style="font-size:0.65rem;color:#64748b;font-weight:500;">Playwright Grid</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:0.35rem;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);padding:2px 7px;border-radius:100px;">
    <span style="width:5px;height:5px;background:#10b981;border-radius:50%;box-shadow:0 0 6px #10b981;"></span>
    <span style="font-size:0.65rem;font-weight:600;color:#10b981;">ONLINE</span>
  </div>
</div>
""", unsafe_allow_html=True)

        # Load persistent sidebar state
        if "sidebar_config_loaded" not in st.session_state:
            saved_cfg = load_saved_sidebar_config()
            st.session_state.cfg_threads = int(saved_cfg.get("threads", 3))
            st.session_state.cfg_limit = int(saved_cfg.get("limit", 15))
            st.session_state.cfg_delay = float(saved_cfg.get("delay", 1.0))
            st.session_state.cfg_enrich = bool(saved_cfg.get("enrich", True))
            st.session_state.cfg_concurrency = int(saved_cfg.get("concurrency", 10))
            st.session_state.cfg_headless = bool(saved_cfg.get("headless", True))
            st.session_state.cfg_use_solver = bool(saved_cfg.get("use_solver", False))
            st.session_state.cfg_solver_ext = str(saved_cfg.get("solver_ext", "captchasonic"))
            st.session_state.cfg_proxy_mode = str(saved_cfg.get("proxy_mode", "Direct IP"))
            st.session_state.cfg_single_proxy = str(saved_cfg.get("single_proxy", ""))
            st.session_state.cfg_rotating_proxies = str(saved_cfg.get("rotating_proxies", ""))
            st.session_state.cfg_proxy_file_path = str(saved_cfg.get("proxy_file_path", ""))
            st.session_state.cfg_enable_ai = bool(saved_cfg.get("enable_ai", True))
            st.session_state.cfg_ollama_endpoint = str(saved_cfg.get("ollama_endpoint", DEFAULT_OLLAMA_ENDPOINT))
            st.session_state.cfg_ollama_model = str(saved_cfg.get("ollama_model", DEFAULT_OLLAMA_MODEL))
            st.session_state.cfg_ai_filter_junk = bool(saved_cfg.get("ai_filter_junk", True))
            st.session_state.cfg_ai_concurrency = int(saved_cfg.get("ai_concurrency", 3))
            st.session_state.sidebar_config_loaded = True

        def _persist_sidebar():
            save_sidebar_config({
                "threads": st.session_state.cfg_threads,
                "limit": st.session_state.cfg_limit,
                "delay": st.session_state.cfg_delay,
                "enrich": st.session_state.cfg_enrich,
                "concurrency": st.session_state.cfg_concurrency,
                "headless": st.session_state.cfg_headless,
                "use_solver": st.session_state.cfg_use_solver,
                "solver_ext": st.session_state.cfg_solver_ext,
                "proxy_mode": st.session_state.cfg_proxy_mode,
                "single_proxy": st.session_state.cfg_single_proxy,
                "rotating_proxies": st.session_state.cfg_rotating_proxies,
                "proxy_file_path": st.session_state.cfg_proxy_file_path,
                "enable_ai": st.session_state.cfg_enable_ai,
                "ollama_endpoint": st.session_state.cfg_ollama_endpoint,
                "ollama_model": st.session_state.cfg_ollama_model,
                "ai_filter_junk": st.session_state.cfg_ai_filter_junk,
                "ai_concurrency": st.session_state.cfg_ai_concurrency,
            })

        # Card 1: Workers & Concurrency
        with st.container(border=True):
            st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
  <span style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#818cf8;">⚡ Worker Threads</span>
  <span style="font-size:0.62rem;background:rgba(99,102,241,0.15);color:#818cf8;padding:1px 5px;border-radius:4px;font-family:'JetBrains Mono',monospace;">PARALLEL</span>
</div>
""", unsafe_allow_html=True)
            threads = st.slider("Workers (Threads)", 1, 12, value=min(st.session_state.cfg_threads, 12),
                                help="Concurrent browser processes running simultaneously.")
            limit   = st.slider("Leads per Query", 1, 100, value=st.session_state.cfg_limit)
            delay   = st.slider("Action Delay (s)", 0.5, 3.0, value=st.session_state.cfg_delay, step=0.1)

            if threads != st.session_state.cfg_threads or limit != st.session_state.cfg_limit or delay != st.session_state.cfg_delay:
                st.session_state.cfg_threads = threads
                st.session_state.cfg_limit = limit
                st.session_state.cfg_delay = delay
                _persist_sidebar()

        # Card 2: Website Enrichment
        with st.container(border=True):
            st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
  <span style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#818cf8;">🔍 Lead Enrichment</span>
  <span style="font-size:0.62rem;background:rgba(99,102,241,0.15);color:#818cf8;padding:1px 5px;border-radius:4px;font-family:'JetBrains Mono',monospace;">CONTACTS</span>
</div>
""", unsafe_allow_html=True)
            enrich = st.toggle("Enrich Website Contacts", value=st.session_state.cfg_enrich)
            if enrich:
                concurrency = st.slider("Enrichment Threads", 1, 50, value=min(st.session_state.cfg_concurrency, 50))
            else:
                concurrency = 20
            headless = st.toggle("Headless Stealth Mode", value=st.session_state.cfg_headless)

            if enrich != st.session_state.cfg_enrich or concurrency != st.session_state.cfg_concurrency or headless != st.session_state.cfg_headless:
                st.session_state.cfg_enrich = enrich
                st.session_state.cfg_concurrency = concurrency
                st.session_state.cfg_headless = headless
                _persist_sidebar()

        # Card 3: Captcha Solver
        with st.container(border=True):
            st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
  <span style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#818cf8;">🛡️ Bit Solver Extension</span>
  <span style="font-size:0.62rem;background:rgba(99,102,241,0.15);color:#818cf8;padding:1px 5px;border-radius:4px;font-family:'JetBrains Mono',monospace;">AUTO</span>
</div>
""", unsafe_allow_html=True)
            use_solver = st.toggle("Auto-Solve CAPTCHAs", value=st.session_state.cfg_use_solver,
                                   help="Injects Bit Solver extension into each worker browser.")
            if use_solver:
                solver_ext = st.segmented_control(
                    "Solver Extension",
                    options=["captchasonic", "nopecha"],
                    default=st.session_state.cfg_solver_ext if st.session_state.cfg_solver_ext in ["captchasonic", "nopecha"] else "captchasonic",
                    label_visibility="collapsed",
                )
            else:
                solver_ext = "captchasonic"

            if use_solver != st.session_state.cfg_use_solver or solver_ext != st.session_state.cfg_solver_ext:
                st.session_state.cfg_use_solver = use_solver
                st.session_state.cfg_solver_ext = solver_ext
                _persist_sidebar()

        # Card 4: Rotating Proxies
        with st.container(border=True):
            st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
  <span style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#818cf8;">🌐 Proxy Network</span>
  <span style="font-size:0.62rem;background:rgba(99,102,241,0.15);color:#818cf8;padding:1px 5px;border-radius:4px;font-family:'JetBrains Mono',monospace;">PERSISTENT</span>
</div>
""", unsafe_allow_html=True)
            proxy_mode = st.segmented_control(
                "Proxy Source",
                options=["Direct IP", "Single Proxy", "Rotating Pool"],
                default=st.session_state.cfg_proxy_mode if st.session_state.cfg_proxy_mode in ["Direct IP", "Single Proxy", "Rotating Pool"] else "Direct IP",
                label_visibility="collapsed",
            )
            if not proxy_mode:
                proxy_mode = "Direct IP"

            if proxy_mode != st.session_state.cfg_proxy_mode:
                st.session_state.cfg_proxy_mode = proxy_mode
                _persist_sidebar()

            proxy_list: List[str] = []
            if proxy_mode == "Single Proxy":
                single = st.text_input(
                    "Proxy URL",
                    value=st.session_state.cfg_single_proxy,
                    placeholder="host:port:username:password",
                    label_visibility="collapsed",
                )
                if single != st.session_state.cfg_single_proxy:
                    st.session_state.cfg_single_proxy = single
                    _persist_sidebar()

                if single.strip():
                    proxy_list = [single.strip()]
                    parsed = parse_proxy_string(single.strip())
                    if parsed:
                        st.caption(f"💾 Saved: `{parsed.get('server')}` (Authenticated)")
                    else:
                        st.caption("💾 Saved")

            elif proxy_mode == "Rotating Pool":
                proxy_text = st.text_area(
                    "Proxies",
                    value=st.session_state.cfg_rotating_proxies,
                    height=80,
                    placeholder="rp.scrapegw.com:6060:user:pass\nhttp://user:pass@host:port",
                    label_visibility="collapsed",
                )
                if proxy_text != st.session_state.cfg_rotating_proxies:
                    st.session_state.cfg_rotating_proxies = proxy_text
                    _persist_sidebar()

                proxy_file_path = st.text_input(
                    "OR file path",
                    value=st.session_state.cfg_proxy_file_path,
                    placeholder="/path/proxies.txt",
                )
                if proxy_file_path != st.session_state.cfg_proxy_file_path:
                    st.session_state.cfg_proxy_file_path = proxy_file_path
                    _persist_sidebar()

                if proxy_text.strip():
                    proxy_list = parse_proxy_list(proxy_text)
                elif proxy_file_path.strip() and os.path.isfile(proxy_file_path.strip()):
                    proxy_list = load_proxies_from_file(proxy_file_path.strip())

                if proxy_list:
                    st.caption(f"💾 Saved: {len(proxy_list)} proxies → round-robin across {threads} workers")

        # Card 5: Local Ollama AI Intelligence
        with st.container(border=True):
            st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
  <span style="font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#818cf8;">🧠 Ollama AI Intelligence</span>
  <span style="font-size:0.62rem;background:rgba(99,102,241,0.15);color:#818cf8;padding:1px 5px;border-radius:4px;font-family:'JetBrains Mono',monospace;">LOCAL</span>
</div>
""", unsafe_allow_html=True)
            enable_ai = st.toggle(
                "Enable Ollama AI",
                value=st.session_state.cfg_enable_ai,
                help="Uses local Ollama models (e.g. qwen2.5vl:7b) to filter junk, clean names, score lead viability, and generate custom pitch angles.",
            )
            ollama_endpoint = st.session_state.cfg_ollama_endpoint
            ollama_model = st.session_state.cfg_ollama_model
            ai_filter_junk = st.session_state.cfg_ai_filter_junk
            ai_concurrency = st.session_state.cfg_ai_concurrency

            if enable_ai:
                ollama_endpoint = st.text_input(
                    "Endpoint",
                    value=st.session_state.cfg_ollama_endpoint,
                    help="URL of your local or remote Ollama server instance",
                )
                is_online, avail_models, status_str = OllamaClient.check_connection_sync(ollama_endpoint)
                if is_online:
                    st.caption(f"🟢 **Ollama:** {status_str}")
                    model_options = list(avail_models) if avail_models else [DEFAULT_OLLAMA_MODEL]
                    if st.session_state.cfg_ollama_model not in model_options:
                        model_options.insert(0, st.session_state.cfg_ollama_model)
                    sel_idx = model_options.index(st.session_state.cfg_ollama_model) if st.session_state.cfg_ollama_model in model_options else 0
                    ollama_model = st.selectbox(
                        "Model",
                        options=model_options,
                        index=sel_idx,
                        help="Select from local Ollama models",
                    )
                else:
                    st.caption(f"🔴 **Ollama:** {status_str}")
                    ollama_model = st.text_input("Model Name", value=st.session_state.cfg_ollama_model)

                c_ai1, c_ai2 = st.columns(2)
                ai_filter_junk = c_ai1.checkbox("🗑️ Drop Junk", value=st.session_state.cfg_ai_filter_junk, help="Automatically drop junk/spam listings")
                ai_concurrency = c_ai2.number_input("AI Threads", min_value=1, max_value=16, value=min(st.session_state.cfg_ai_concurrency, 16), help="Parallel Ollama requests (optimal: 6 for RX 9060 XT)")

            if (enable_ai != st.session_state.cfg_enable_ai or
                ollama_endpoint != st.session_state.cfg_ollama_endpoint or
                ollama_model != st.session_state.cfg_ollama_model or
                ai_filter_junk != st.session_state.cfg_ai_filter_junk or
                ai_concurrency != st.session_state.cfg_ai_concurrency):
                st.session_state.cfg_enable_ai = enable_ai
                st.session_state.cfg_ollama_endpoint = ollama_endpoint
                st.session_state.cfg_ollama_model = ollama_model
                st.session_state.cfg_ai_filter_junk = ai_filter_junk
                st.session_state.cfg_ai_concurrency = int(ai_concurrency)
                _persist_sidebar()

        # Card 6: Bottom Cluster Telemetry HUD
        solver_status_color = "#10b981" if use_solver else "#64748b"
        solver_status_text  = "Armed" if use_solver else "Disabled"
        proxy_count_display = f"{len(proxy_list)} IP{'s' if len(proxy_list) != 1 else ''}" if proxy_list else "Direct"
        ai_hud_text = f"Ollama ({ollama_model[:12]})" if enable_ai else "Disabled"
        ai_hud_color = "#10b981" if enable_ai else "#64748b"

        st.markdown(f"""
<div style="background:rgba(10,10,18,0.7);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:0.75rem 0.85rem;margin-top:0.2rem;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
    <span style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;">Node Telemetry</span>
    <span style="font-size:0.62rem;color:#10b981;font-weight:600;display:flex;align-items:center;gap:3px;font-family:'JetBrains Mono',monospace;">
      <span style="width:5px;height:5px;background:#10b981;border-radius:50%;display:inline-block;box-shadow:0 0 5px #10b981;"></span>
      HEALTHY
    </span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.35rem;font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:#94a3b8;">
    <div>Workers: <span style="color:#f8fafc;font-weight:600;">{threads}</span></div>
    <div>Limit: <span style="color:#f8fafc;font-weight:600;">{limit}/q</span></div>
    <div>Proxies: <span style="color:#818cf8;font-weight:600;">{proxy_count_display}</span></div>
    <div>Solver: <span style="color:{solver_status_color};font-weight:600;">{solver_status_text}</span></div>
    <div style="grid-column:1/-1;">AI Gen: <span style="color:{ai_hud_color};font-weight:600;">{ai_hud_text}</span></div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Session State & Checkpoint Recovery ───────────────────────────────────
    if "leads" not in st.session_state:
        st.session_state.leads = []
    if "running" not in st.session_state:
        st.session_state.running = False
    if "is_paused" not in st.session_state:
        st.session_state.is_paused = False
    if "resume_triggered" not in st.session_state:
        st.session_state.resume_triggered = False

    saved_session = load_session_checkpoint()
    has_active_session = bool(
        saved_session and
        saved_session.get("status") in ["running", "paused"] and
        (saved_session.get("leads") or saved_session.get("pending_queries"))
    )

    if has_active_session and not st.session_state.running:
        status_tag = saved_session.get("status", "interrupted").upper()
        n_leads = len(saved_session.get("leads", []))
        n_pending = len(saved_session.get("pending_queries", []))
        n_completed = len(saved_session.get("completed_queries", []))

        with st.container(border=True):
            st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
  <span style="font-size:0.82rem;font-weight:700;color:#f59e0b;letter-spacing:0.04em;">⚠️ RECOVERED SCRAPING SESSION ({status_tag})</span>
  <span style="font-size:0.68rem;background:rgba(245,158,11,0.15);color:#f59e0b;padding:2px 8px;border-radius:6px;font-family:'JetBrains Mono',monospace;">{n_leads} LEADS PRESERVED</span>
</div>
<p style="font-size:0.78rem;color:#94a3b8;margin:0 0 0.6rem;">
A previous scrape session was saved on disk (e.g. from a browser refresh, interruption, or pause). You can resume the remaining <b>{n_pending}</b> queries or keep the <b>{n_leads}</b> collected leads.
</p>
""", unsafe_allow_html=True)
            rec_c1, rec_c2, rec_c3 = st.columns([1.2, 1.2, 1])
            with rec_c1:
                if n_pending > 0:
                    if st.button(f"▶️ Resume Scraping ({n_pending} Queries)", type="primary", use_container_width=True):
                        st.session_state.resume_triggered = True
                        st.rerun()
            with rec_c2:
                if n_leads > 0:
                    if st.button(f"✅ Keep {n_leads} Leads & Finish", use_container_width=True):
                        st.session_state.leads = [BusinessLead(**d) for d in saved_session.get("leads", [])]
                        clear_session_checkpoint()
                        st.rerun()
            with rec_c3:
                if st.button("🗑️ Discard Session", use_container_width=True):
                    clear_session_checkpoint()
                    st.rerun()

    # ── Query Input Container ─────────────────────────────────────────────────
    with st.container(border=True):
        query_mode = st.segmented_control(
            "Search Mode",
            options=["🔍 Single Query", "📋 Batch Queries", "🌍 Global City Expander (1,000+ Leads)"],
            default="🔍 Single Query",
            label_visibility="collapsed",
        )
        if not query_mode:
            query_mode = "🔍 Single Query"

        # Preset suggestions state
        if "selected_query_preset" not in st.session_state:
            st.session_state.selected_query_preset = ""

        active_queries: List[str] = []

        if query_mode == "🔍 Single Query":
            single_query = st.text_input(
                "Search Query",
                value=st.session_state.selected_query_preset,
                placeholder="e.g. Dentists in Austin, TX  or  Plumbers in London, UK",
                label_visibility="collapsed",
            )

            # Quick Suggestion Chips
            st.markdown("""
<div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;margin-top:0.4rem;margin-bottom:0.2rem;">
  <span style="font-size:0.7rem;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-right:0.2rem;">Quick Fill:</span>
</div>
""", unsafe_allow_html=True)

            chip_col1, chip_col2, chip_col3, chip_col4, chip_col5 = st.columns(5)
            if chip_col1.button("🔥 Plumbers Austin, TX", use_container_width=True):
                st.session_state.selected_query_preset = "Plumbers in Austin, TX"
                st.rerun()
            if chip_col2.button("🦷 Dentists London, UK", use_container_width=True):
                st.session_state.selected_query_preset = "Dentists in London, UK"
                st.rerun()
            if chip_col3.button("🏗️ Roofers Miami, FL", use_container_width=True):
                st.session_state.selected_query_preset = "Roofers in Miami, FL"
                st.rerun()
            if chip_col4.button("💻 Web Design Dubai", use_container_width=True):
                st.session_state.selected_query_preset = "Web Designers in Dubai, UAE"
                st.rerun()
            if chip_col5.button("⚖️ Lawyers Toronto", use_container_width=True):
                st.session_state.selected_query_preset = "Lawyers in Toronto, ON"
                st.rerun()

            if single_query.strip():
                active_queries = [single_query.strip()]

        elif query_mode == "📋 Batch Queries":
            batch_text = st.text_area(
                "Queries (one per line)",
                placeholder="Dentists in Austin, TX\nRoofers in Miami, FL\nMarketing Agencies in London, UK\nCafes in Berlin, Germany",
                height=130,
                label_visibility="collapsed",
            )
            if batch_text.strip():
                active_queries = [q.strip() for q in batch_text.splitlines() if q.strip()]

        else:
            # 🌍 Global City Expander Mode
            st.markdown("""
<p style="font-size:0.82rem;color:#64748b;margin:0 0 0.8rem;">
Split any city worldwide into postal zones or business districts to bypass Google Maps' ~120 cap and capture 1,000+ leads.
</p>
""", unsafe_allow_html=True)
            col_g1, col_g2 = st.columns([1, 1])
            with col_g1:
                geo_niche = st.text_input("Niche / Category", placeholder="Plumbers, Dentists, Roofers", value="Plumbers")
                geo_country_choice = st.selectbox(
                    "Country Override (Optional)",
                    [
                        "Auto-Detect from Location (Recommended)",
                        "US (United States)",
                        "GB (United Kingdom / England)",
                        "CA (Canada)",
                        "AU (Australia)",
                        "AE (United Arab Emirates / Dubai)",
                        "DE (Germany)",
                        "FR (France)",
                        "IN (India)",
                        "ES (Spain)",
                        "IT (Italy)",
                        "NL (Netherlands)",
                        "NZ (New Zealand)",
                        "SG (Singapore)",
                        "BR (Brazil)",
                        "MX (Mexico)",
                        "ZA (South Africa)",
                        "Other / 80+ Countries",
                    ],
                    index=0,
                )
            with col_g2:
                geo_loc = st.text_input(
                    "City & Location (Worldwide)",
                    placeholder="e.g. London, UK  |  Dubai, UAE  |  Austin, TX  |  Sydney, Australia  |  DNH, IN",
                    value="London, UK",
                    help="Enter any city worldwide. Country is automatically detected from suffix.",
                )
                geo_limit = st.slider("Sub-Queries to Generate", 3, 50, 10, help="Number of sub-queries across postal zones")

            if geo_country_choice.startswith("Auto-Detect"):
                country_code = None
            else:
                country_code = geo_country_choice[:2].lower()

            if "geo_queries" not in st.session_state:
                st.session_state.geo_queries = ""

            if st.button("⚡ Generate Global Sub-Queries"):
                if geo_niche.strip() and geo_loc.strip():
                    sub_list = generate_sub_queries(geo_niche, geo_loc, country=country_code, limit=geo_limit)
                    st.session_state.geo_queries = "\n".join(sub_list)
                    st.success(f"✅ Generated {len(sub_list)} sub-queries across {geo_loc}!")
                else:
                    st.warning("Please enter both Niche and City/Location.")

            geo_batch_text = st.text_area(
                "Generated Sub-Queries (Editable):",
                value=st.session_state.geo_queries,
                height=120,
                placeholder="Click 'Generate Global Sub-Queries' above or launch directly.",
            )

            if geo_batch_text.strip():
                active_queries = [q.strip() for q in geo_batch_text.splitlines() if q.strip()]
            elif geo_niche.strip() and geo_loc.strip():
                # Auto-generate on the fly if user didn't click generate button!
                active_queries = generate_sub_queries(geo_niche, geo_loc, country=country_code, limit=geo_limit)

        q_count = len(active_queries)
        button_label = f"🚀 Launch Scraper — {q_count} Target Quer{'ies' if q_count != 1 else 'y'}" if q_count > 0 else "🚀 Launch Scraper"

        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        start_btn = st.button(button_label, type="primary", use_container_width=True)
        if start_btn and q_count == 0:
            st.warning("⚠️ Please enter a search query above before clicking Launch Scraper.")

    # ── Pipeline Execution (New Launch or Resume) ─────────────────────────────
    is_resuming = st.session_state.get("resume_triggered", False)
    if (start_btn or is_resuming) and not st.session_state.running:
        if is_resuming:
            st.session_state.resume_triggered = False
            saved_sess = load_session_checkpoint() or {}
            queries = saved_sess.get("pending_queries", [])
            initial_leads = [BusinessLead(**d) for d in saved_sess.get("leads", [])]
            all_target_queries = saved_sess.get("queries", []) or queries
        else:
            queries = active_queries
            initial_leads = []
            all_target_queries = list(queries)

        if not queries:
            st.warning("⚠️ Please enter or select at least one search query.")
            return

        st.session_state.running = True
        st.session_state.leads = initial_leads
        st.session_state.last_scrape_attempted = False
        st.session_state.is_paused = False

        lead_queue: Queue = Queue()
        result_queue: Queue = Queue()
        stop_event = threading.Event()
        st.session_state.stop_event = stop_event

        chk_cfg = {
            "limit": limit,
            "threads": threads,
            "headless": headless,
            "delay": delay,
            "enrich": enrich,
            "enable_ai": enable_ai,
            "ollama_model": ollama_model,
        }

        t = threading.Thread(
            target=run_pool_in_thread,
            args=(queries, limit, threads, headless, delay,
                  proxy_list, use_solver, solver_ext,
                  lead_queue, result_queue, stop_event,
                  initial_leads, all_target_queries, chk_cfg),
            daemon=True,
        )
        t.start()

        # ── Live Progress Display ─────────────────────────────────────────────
        col_hdr, col_stop = st.columns([3, 1])
        with col_hdr:
            section_header("Live Harvesting Telemetry")
        with col_stop:
            st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)
            if st.button("⏹️ Stop / Pause Scraper", type="secondary", use_container_width=True, help="Stop remaining queries and save current leads"):
                stop_event.set()

        query_statuses = {q: st.empty() for q in queries}
        for q in queries:
            query_statuses[q].info(f"⏳ Queued in pool: **{q}**")

        overall_bar = st.progress(0.0, text="Initialising Playwright cluster…")
        live_counter = st.empty()
        total_found = len(initial_leads)
        workers_done = 0

        live_raw_leads = list(initial_leads)
        was_paused = False

        while True:
            try:
                msg = lead_queue.get(timeout=0.3)
                kind = msg[0]

                if kind == "lead":
                    _, wid, lead = msg
                    total_found += 1
                    live_raw_leads.append(lead)
                    unique_count = len(deduplicate_leads(live_raw_leads))
                    q = lead.search_query
                    if q in query_statuses:
                        query_statuses[q].info(
                            f"🔄 **[Worker {wid}]** Scraping **{q}** — Latest: *{lead.name}*"
                        )
                    live_counter.metric(
                        "Unique Leads Captured",
                        unique_count,
                        help=f"Total raw records gathered across all workers: {total_found} (auto-deduplicated)",
                    )
                    overall_bar.progress(
                        min(unique_count / max(limit * len(all_target_queries), 1), 0.95),
                        text=f"Harvesting… {unique_count} unique leads ({total_found} raw collected)",
                    )

                elif kind == "worker_done":
                    _, wid, result = msg
                    workers_done += 1
                    q = result.query
                    proxy_tag = f" via `{result.proxy[:30]}…`" if result.proxy else ""
                    if result.error and "stop" not in result.error.lower():
                        query_statuses[q].error(
                            f"❌ **[Worker {wid}]** **{q}** — Error: {result.error[:60]}"
                        )
                    elif result.error:
                        query_statuses[q].warning(
                            f"⏹️ **[Worker {wid}]** **{q}** — Paused"
                        )
                    else:
                        query_statuses[q].success(
                            f"✅ **[Worker {wid}]** **{q}**{proxy_tag} — "
                            f"**{len(result.leads)} leads** in {result.duration_sec:.1f}s"
                        )

            except Empty:
                pass

            try:
                done_msg = result_queue.get_nowait()
                msg_type = done_msg[0]
                if msg_type in ["done", "paused"]:
                    _, unique_leads, worker_results = done_msg
                    was_paused = (msg_type == "paused")
                    tag_txt = "⏸️ Scraping paused" if was_paused else "✅ Scraping phase complete!"
                    overall_bar.progress(1.0, text=tag_txt)
                    break
                elif msg_type == "error":
                    _, unique_leads, worker_results = done_msg
                    overall_bar.progress(1.0, text="❌ Error during scraping")
                    break
            except Empty:
                pass

            if not t.is_alive():
                try:
                    done_msg = result_queue.get(timeout=2)
                    msg_type = done_msg[0]
                    if msg_type in ["done", "paused"]:
                        _, unique_leads, worker_results = done_msg
                        was_paused = (msg_type == "paused")
                    else:
                        unique_leads, worker_results = [], []
                except Empty:
                    unique_leads, worker_results = [], []
                overall_bar.progress(1.0, text="✅ Done")
                break

        # ── Enrichment Phase ──────────────────────────────────────────────────
        if enrich and unique_leads:
            enrich_bar  = st.progress(0.0, text="Enriching website contacts (emails & socials)…")
            enrich_stat = st.empty()
            enriched_count = [0]

            def _enrich_callback(lead: BusinessLead):
                enriched_count[0] += 1
                enrich_bar.progress(
                    min(enriched_count[0] / max(len(unique_leads), 1), 1.0),
                    text=f"Enriched {enriched_count[0]}/{len(unique_leads)} — {lead.name[:30]}",
                )
                email_display = lead.primary_email or "no email found"
                enrich_stat.caption(f"Latest: **{lead.name}** → `{email_display}`")

            async def _run_enrich():
                enricher = WebsiteEnricher(
                    concurrency=concurrency,
                    proxy=proxy_list[0] if proxy_list else None,
                )
                return await enricher.enrich_leads_batch(unique_leads, progress_callback=_enrich_callback)

            try:
                unique_leads = asyncio.run(_run_enrich())
                enrich_bar.progress(1.0, text="✅ Contact enrichment complete!")
            except Exception:
                pass

        # ── Ollama AI Lead Intelligence Phase ─────────────────────────────────
        if enable_ai and unique_leads:
            ai_bar  = st.progress(0.0, text=f"🤖 Analyzing leads with Ollama ({ollama_model})…")
            ai_stat = st.empty()

            def _ai_callback(lead: BusinessLead, done_c: int, total_c: int):
                ai_bar.progress(
                    min(done_c / max(total_c, 1), 1.0),
                    text=f"🤖 AI analyzed {done_c}/{total_c} leads — {lead.ai_cleaned_name or lead.name}",
                )
                tag = "🗑️ [Junk]" if lead.ai_is_junk else f"⭐ [Score {lead.ai_lead_score or 'N/A'}/10]"
                ai_stat.caption(f"Latest: **{lead.ai_cleaned_name or lead.name}** → `{tag}`: {lead.ai_pitch_angle or lead.ai_summary or ''}")

            async def _run_ai_pipeline():
                client = OllamaClient(
                    endpoint=ollama_endpoint,
                    model=ollama_model,
                    concurrency=int(ai_concurrency),
                )
                return await client.process_leads_batch(
                    unique_leads,
                    progress_callback=_ai_callback,
                    filter_junk=ai_filter_junk,
                )

            try:
                unique_leads = asyncio.run(_run_ai_pipeline())
                ai_bar.progress(1.0, text=f"✅ Ollama AI intelligence complete! ({len(unique_leads)} leads ready)")
            except Exception as e:
                st.error(f"Ollama AI processing error: {e}")

        st.session_state.leads = unique_leads
        st.session_state.running = False
        st.session_state.last_scrape_attempted = (len(unique_leads) == 0)
        st.session_state.last_scrape_queries = all_target_queries
        st.session_state.is_paused = was_paused

        if not was_paused:
            clear_session_checkpoint()
        st.rerun()

    # ── If Idle: Show Feedback or 3D Interactive Bento Grid ───────────────────
    if not st.session_state.running and not st.session_state.leads:
        if st.session_state.get("last_scrape_attempted"):
            qs = st.session_state.get("last_scrape_queries", [])
            qs_str = ", ".join(f"**{q}**" for q in qs[:3]) + (f" and {len(qs)-3} more" if len(qs) > 3 else "")
            col_warn, col_clear = st.columns([5, 1])
            with col_warn:
                st.warning(
                    f"⚠️ The scraper finished, but **0 leads** were captured for: {qs_str}.\n\n"
                    "**Quick Troubleshooting Tips:**\n"
                    "• **Google Bot Detection / CAPTCHA:** Try toggling **OFF** *'Headless Stealth Mode'* in the sidebar to view the browser window in real time, or toggle **ON** *'Auto-Solve CAPTCHAs'*.\n"
                    "• **Search Formatting:** Make sure the query is in the format: `Niche in City, Country` (e.g. `Restaurants in Silvassa, DNH` or `Dentists in Austin, TX`).\n"
                    "• **IP Rate Limiting:** Add rotating proxies in the sidebar under *Proxy Network*."
                )
            with col_clear:
                st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
                if st.button("✕ Dismiss", use_container_width=True):
                    st.session_state.last_scrape_attempted = False
                    st.rerun()

        section_header("Engine Architecture & Core Capabilities")

        st.markdown("""
<div class="bento-grid">
  <!-- Card 1: Multi-Worker Pool -->
  <div class="bento-card">
    <div class="bento-card-sheen"></div>
    <div class="bento-icon">⚡</div>
    <div class="bento-tag">Concurrency</div>
    <div class="bento-heading">Multi-Worker Pool</div>
    <p class="bento-desc">
      Orchestrates concurrent Playwright browser workers with asynchronous queues and dedicated proxy routing.
    </p>
    <div class="bento-footer">
      <span class="bento-stat">1–10 Workers</span>
      <span class="bento-badge">Round-Robin</span>
    </div>
  </div>

  <!-- Card 2: Web Builder Prospector -->
  <div class="bento-card">
    <div class="bento-card-sheen"></div>
    <div class="bento-icon">🎯</div>
    <div class="bento-tag">Lead Quality</div>
    <div class="bento-heading">Web Builder Mode</div>
    <p class="bento-desc">
      Pinpoints verified businesses with <b>No Website</b>, while verifying phone numbers, direct emails, and active socials.
    </p>
    <div class="bento-footer">
      <span class="bento-stat">Zero-Website Filter</span>
      <span class="bento-badge">Prime Targets</span>
    </div>
  </div>

  <!-- Card 3: Global Geo-Expander -->
  <div class="bento-card">
    <div class="bento-card-sheen"></div>
    <div class="bento-icon">🌍</div>
    <div class="bento-tag">Scale Past 120</div>
    <div class="bento-heading">Global Geo-Expander</div>
    <p class="bento-desc">
      Splits cities into postal zones & business districts worldwide (US, UK, Canada, Australia, UAE, Europe, 90+ countries).
    </p>
    <div class="bento-footer">
      <span class="bento-stat">1,000+ Leads/City</span>
      <span class="bento-badge">Postal Zones</span>
    </div>
  </div>

  <!-- Card 4: Bit Solver Stealth -->
  <div class="bento-card">
    <div class="bento-card-sheen"></div>
    <div class="bento-icon">🛡️</div>
    <div class="bento-tag">Anti-Bot Shield</div>
    <div class="bento-heading">Bit Solver Suite</div>
    <p class="bento-desc">
      Auto-solves reCAPTCHA v2 and Cloudflare challenges using the Bit Solver extension with auto-reload recovery.
    </p>
    <div class="bento-footer">
      <span class="bento-stat">Auto-Inject</span>
      <span class="bento-badge">Zero Crash</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Results & Web Builder Filtering ───────────────────────────────────────
    if st.session_state.leads:
        unique_leads = st.session_state.leads
        total_raw    = len(unique_leads)
        no_web_raw   = sum(1 for l in unique_leads if not l.has_website)
        has_web_raw  = sum(1 for l in unique_leads if l.has_website)

        section_header("🎯 Lead Intelligence & Web Builder Mode")

        # 1-Click AI trigger for current harvested leads
        col_ai_btn, col_ai_info = st.columns([1, 2])
        with col_ai_btn:
            if st.button("🤖 Run Ollama AI on Current Leads", use_container_width=True, help=f"Analyze & filter these leads with {ollama_model}"):
                ai_prog = st.progress(0.0, text=f"🤖 Analyzing {len(unique_leads)} leads with Ollama ({ollama_model})…")
                
                def _manual_ai_cb(l, done_c, tot_c):
                    ai_prog.progress(min(done_c / max(tot_c, 1), 1.0), text=f"AI Analyzed {done_c}/{tot_c} leads…")

                async def _run_manual_ai():
                    c = OllamaClient(endpoint=ollama_endpoint, model=ollama_model, concurrency=int(ai_concurrency))
                    return await c.process_leads_batch(unique_leads, progress_callback=_manual_ai_cb, filter_junk=ai_filter_junk)

                with st.spinner(f"Analyzing leads with Ollama ({ollama_model})..."):
                    updated = asyncio.run(_run_manual_ai())
                    st.session_state.leads = updated
                    st.rerun()

        with col_ai_info:
            ai_analyzed_count = sum(1 for l in unique_leads if l.ai_lead_score is not None)
            if ai_analyzed_count > 0:
                st.caption(f"✨ **AI Status:** {ai_analyzed_count}/{total_raw} leads analyzed & scored with `{ollama_model}`")
            else:
                st.caption(f"💡 Leads not AI-analyzed yet. Click **Run Ollama AI on Current Leads** to analyze now.")

        filter_col1, filter_col2 = st.columns([1, 1])
        with filter_col1:
            web_mode = st.radio(
                "Filter by Website Status:",
                [
                    f"🎯 No Website Only — Web Design Targets ({no_web_raw})",
                    f"📋 All Scraped Leads ({total_raw})",
                    f"🌐 Has Website ({has_web_raw})",
                ],
                index=0,
            )

        with filter_col2:
            st.markdown("""<p style="font-size:0.75rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:#64748b;margin-bottom:0.4rem;">Contact Channel Quality</p>""", unsafe_allow_html=True)
            req_contact = st.checkbox(
                "✅ At least 1 Contact (Phone or Email) OR 1 Social Media Handle",
                value=True,
                help="Drops uncontactable leads that have no phone, email, or social profiles.",
            )
            req_phone_email = st.checkbox(
                "📞+✉️ Must have BOTH Phone and Email linked",
                value=False,
                help="Only keep leads with both a verified phone and email.",
            )
            c_phone, c_email = st.columns(2)
            req_phone = c_phone.checkbox("📞 Phone Required", value=False)
            req_email = c_email.checkbox("✉️ Email Required", value=False)
            
            c_rev, c_ai = st.columns(2)
            min_rev_input = c_rev.slider("💬 Min Reviews", 0, 100, 0, help="Only show businesses with at least this many Google reviews")
            min_ai_input = c_ai.slider("⭐ Min AI Score", 0, 10, 0, help="Filter leads by Ollama AI viability score (1-10)")

            exclude_ai_junk = st.checkbox("🗑️ Exclude AI-Flagged Junk", value=True, help="Hide spam, closed, or non-commercial listings")

        if "No Website Only" in web_mode:
            active_web_filter = "no_website"
        elif "Has Website" in web_mode:
            active_web_filter = "has_website"
        else:
            active_web_filter = "all"

        filtered_leads = filter_leads(
            unique_leads,
            require_contact=req_contact,
            website_filter=active_web_filter,
            require_phone_and_email=req_phone_email,
            require_phone=req_phone,
            require_email=req_email,
            min_reviews=min_rev_input if min_rev_input > 0 else None,
            exclude_junk=exclude_ai_junk,
            min_ai_score=min_ai_input if min_ai_input > 0 else None,
        )

        # 3D Interactive Telemetry Stat Cards
        f_total   = len(filtered_leads)
        f_no_web  = sum(1 for l in filtered_leads if not l.has_website)
        f_phone   = sum(1 for l in filtered_leads if l.has_phone)
        f_email   = sum(1 for l in filtered_leads if l.has_email)
        f_reviews = sum(l.review_count or 0 for l in filtered_leads)
        rated_leads = [l for l in filtered_leads if l.rating]
        avg_rating = round(sum(l.rating for l in rated_leads) / len(rated_leads), 1) if rated_leads else 0.0
        ai_scored_leads = [l for l in filtered_leads if l.ai_lead_score]
        avg_ai_score = round(sum(l.ai_lead_score for l in ai_scored_leads) / len(ai_scored_leads), 1) if ai_scored_leads else 0.0

        ai_score_card = f"""
  <div class="stat-box">
    <div class="stat-box-label">🧠 Avg AI Score</div>
    <div class="stat-box-num accent">{avg_ai_score}/10</div>
  </div>""" if ai_scored_leads else ""

        st.markdown(f"""
<div class="stat-card-grid">
  <div class="stat-box">
    <div class="stat-box-label">Filtered Leads</div>
    <div class="stat-box-num accent">{f_total}</div>
  </div>
  <div class="stat-box">
    <div class="stat-box-label">🎯 No Website</div>
    <div class="stat-box-num accent">{f_no_web}</div>
  </div>
  <div class="stat-box">
    <div class="stat-box-label">💬 Total Reviews</div>
    <div class="stat-box-num green">{f_reviews:,}</div>
  </div>
  <div class="stat-box">
    <div class="stat-box-label">⭐ Avg Rating</div>
    <div class="stat-box-num amber">{avg_rating}</div>
  </div>
  <div class="stat-box">
    <div class="stat-box-label">📞 Phone</div>
    <div class="stat-box-num">{f_phone}</div>
  </div>
  <div class="stat-box">
    <div class="stat-box-label">✉️ Email</div>
    <div class="stat-box-num">{f_email}</div>
  </div>
{ai_score_card}
</div>
""", unsafe_allow_html=True)

        if not filtered_leads:
            st.warning("⚠️ No leads match the selected filter combination. Try unchecking some contact requirements.")
        else:
            records = [l.to_flat_dict() for l in filtered_leads]
            df = pd.DataFrame(records)

            all_cols = df.columns.tolist()
            default_cols = [
                "Business Name", "Category", "AI Lead Score", "AI Pitch Angle", "Review Count", "Rating", "Has Website", "Phone", "Email",
                "Contact Channels", "City", "State", "Instagram", "Facebook", "LinkedIn"
            ]
            visible_cols = st.multiselect(
                "Visible Columns",
                all_cols,
                default=[c for c in default_cols if c in all_cols],
            )
            st.dataframe(df[visible_cols] if visible_cols else df, use_container_width=True)

            # Export Action Row
            section_header("Export Verified Prospect List")

            prefix = "web_design_prospects" if active_web_filter == "no_website" else "google_maps_leads"
            d1, d2, d3 = st.columns(3)

            csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            d1.download_button(
                f"⬇️ Download CSV ({f_total})",
                data=csv_bytes,
                file_name=f"{prefix}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            xlsx_buf = io.BytesIO()
            with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Leads")
            d2.download_button(
                f"⬇️ Download Excel ({f_total})",
                data=xlsx_buf.getvalue(),
                file_name=f"{prefix}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            json_bytes = df.to_json(orient="records", indent=2).encode("utf-8")
            d3.download_button(
                f"⬇️ Download JSON ({f_total})",
                data=json_bytes,
                file_name=f"{prefix}.json",
                mime="application/json",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
