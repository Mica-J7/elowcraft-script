"""Streamlit UI for chat-based highlight detection on Twitch VODs."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_highlights import (
    BASELINE_WINDOW_BINS,
    BIN_SIZE_S,
    CLIP_POST_ROLL_S,
    CLIP_PRE_ROLL_S,
    DEFAULT_TOOL_PATH,
    LEAD_OFFSET_S,
    MERGE_GAP_S,
    MIN_SPIKE_COUNT,
    ROOT,
    SPIKE_RATIO,
    build_bins,
    build_report,
    build_vod_url,
    clip_window,
    delete_vod_all,
    delete_vod_chat,
    delete_vod_clips,
    detect_spike_bins,
    download_chat,
    download_clip,
    enrich_moment,
    extract_vod_id,
    format_size,
    format_timecode,
    format_twitch_link,
    list_vod_entries,
    load_comments,
    merge_into_moments,
)

st.set_page_config(page_title="Elowcraft - Chat Highlights", layout="wide")
st.title("Détection de moments forts (chat Twitch)")


def clear_session_if_current(vod_id: str) -> None:
    if st.session_state.get("vod_id") == vod_id:
        for key in ("moments", "vod_id", "vod_input", "lead_offset", "bin_size", "clip_paths"):
            st.session_state.pop(key, None)


with st.sidebar:
    st.header("Paramètres de détection")
    bin_size = st.number_input("Taille des fenêtres (s)", value=BIN_SIZE_S, min_value=5, max_value=60, step=5)
    ratio_threshold = st.slider("Seuil de pic (x baseline)", 1.5, 8.0, float(SPIKE_RATIO), 0.5)
    min_count = st.slider("Messages minimum dans la fenêtre", 5, 50, MIN_SPIKE_COUNT, 1)
    merge_gap = st.number_input("Fusion des pics proches (s)", value=MERGE_GAP_S, min_value=0, max_value=120, step=5)
    lead_offset = st.number_input("Décalage avant le pic (s)", value=LEAD_OFFSET_S, min_value=0, max_value=60, step=5)

    st.header("Paramètres des clips")
    pre_roll = st.number_input("Marge avant le clip (s)", value=CLIP_PRE_ROLL_S, min_value=0, max_value=60, step=5)
    post_roll = st.number_input("Marge après le clip (s)", value=CLIP_POST_ROLL_S, min_value=0, max_value=60, step=5)

tab_analyse, tab_data = st.tabs(["Analyse", "Gestion des données"])

with tab_analyse:
    with st.form("vod_form"):
        vod_input = st.text_input("URL ou ID de la VOD Twitch", placeholder="https://www.twitch.tv/videos/...")
        force_redownload = st.checkbox("Forcer le re-téléchargement du chat", value=False)
        submitted = st.form_submit_button("Valider", type="primary")

    if submitted and not vod_input:
        st.warning("Merci de renseigner une URL ou un ID de VOD.")

    if submitted and vod_input:
        vod_id = extract_vod_id(vod_input)
        chat_path = ROOT / "data" / f"{vod_id}_chat.json"

        if force_redownload or not chat_path.exists():
            with st.spinner("Téléchargement du chat Twitch..."):
                download_chat(vod_input, chat_path, DEFAULT_TOOL_PATH)
        else:
            st.info(f"Chat déjà téléchargé, réutilisation de {chat_path.name}")

        with st.spinner("Analyse en cours..."):
            comments = load_comments(chat_path)
            bins = build_bins(comments, bin_size)
            spike_bins = detect_spike_bins(bins, BASELINE_WINDOW_BINS, ratio_threshold, min_count)
            moments = merge_into_moments(spike_bins, bins, bin_size, merge_gap)
            moments = [enrich_moment(m, comments) for m in moments]

        st.session_state["moments"] = moments
        st.session_state["vod_id"] = vod_id
        st.session_state["vod_input"] = vod_input
        st.session_state["lead_offset"] = lead_offset
        st.session_state["bin_size"] = bin_size
        st.session_state["clip_paths"] = {}

    if "moments" in st.session_state:
        moments = st.session_state["moments"]
        vod_id = st.session_state["vod_id"]
        lead_offset = st.session_state["lead_offset"]
        result_bin_size = st.session_state["bin_size"]
        clip_paths = st.session_state.setdefault("clip_paths", {})

        st.success(f"{len(moments)} moment(s) détecté(s)")

        for i, m in enumerate(moments, 1):
            suggested_s = max(0, m["peak_s"] - lead_offset)
            link = format_twitch_link(vod_id, suggested_s)
            with st.container(border=True):
                col1, col2 = st.columns([1, 4])
                with col1:
                    st.markdown(f"**#{i} &nbsp;&nbsp; [{format_timecode(suggested_s)}]({link})**")
                    st.caption(f"{m['peak_count']} msg / {result_bin_size}s · {m['message_count']} msg total")
                    if i not in clip_paths:
                        if st.button("Télécharger ce clip", key=f"dl_clip_{i}"):
                            clip_dir = ROOT / "data" / "clips" / vod_id
                            clip_dir.mkdir(parents=True, exist_ok=True)
                            start_s, end_s = clip_window(m, lead_offset, pre_roll, post_roll)
                            filename = f"{i:02d}_{format_timecode(start_s).replace(':', '-')}.mp4"
                            output_path = clip_dir / filename
                            with st.spinner("Téléchargement du clip..."):
                                download_clip(build_vod_url(st.session_state["vod_input"]), start_s, end_s, output_path)
                            clip_paths[i] = output_path
                            st.rerun()
                with col2:
                    if m["top_emotes"]:
                        emotes_str = ", ".join(f"`{name}` x{count}" for name, count in m["top_emotes"])
                        st.markdown(f"Émotes : {emotes_str}")
                    for msg in m["sample_messages"]:
                        st.text(msg)
                    if i in clip_paths:
                        st.video(str(clip_paths[i]))

        report = build_report(moments, vod_id, lead_offset)
        st.download_button("Télécharger le rapport (.txt)", report, file_name=f"{vod_id}_highlights.txt")

        st.divider()
        remaining = [(i, m) for i, m in enumerate(moments, 1) if i not in clip_paths]
        if remaining:
            est_minutes = max(1, round(len(remaining) * 0.8))
            if st.button(f"Télécharger les {len(remaining)} clips restants (~{est_minutes} min estimées)"):
                clip_dir = ROOT / "data" / "clips" / vod_id
                clip_dir.mkdir(parents=True, exist_ok=True)
                vod_url = build_vod_url(st.session_state["vod_input"])
                progress_bar = st.progress(0, text="Téléchargement des clips...")

                for done, (idx, m) in enumerate(remaining, 1):
                    start_s, end_s = clip_window(m, lead_offset, pre_roll, post_roll)
                    filename = f"{idx:02d}_{format_timecode(start_s).replace(':', '-')}.mp4"
                    output_path = clip_dir / filename
                    download_clip(vod_url, start_s, end_s, output_path)
                    clip_paths[idx] = output_path
                    progress_bar.progress(done / len(remaining), text=f"Clip {done}/{len(remaining)} téléchargé")
                st.rerun()
        else:
            st.caption("Tous les clips ont déjà été téléchargés.")

with tab_data:
    st.subheader("Données téléchargées")
    entries = list_vod_entries()

    if not entries:
        st.caption("Aucune donnée téléchargée pour le moment.")
    else:
        total_all = sum(e["total_size"] for e in entries)
        st.caption(f"{len(entries)} VOD(s) · {format_size(total_all)} au total")

        for e in entries:
            with st.container(border=True):
                col1, col2 = st.columns([2, 3])
                with col1:
                    st.markdown(f"**VOD {e['vod_id']}**")
                    chat_label = format_size(e["chat_size"]) if e["has_chat"] else "absent"
                    st.caption(
                        f"Chat : {chat_label} · "
                        f"Clips : {e['clip_count']} ({format_size(e['clips_size'])}) · "
                        f"Total : {format_size(e['total_size'])}"
                    )
                with col2:
                    bcol1, bcol2, bcol3 = st.columns(3)
                    if bcol1.button("Supprimer les clips", key=f"del_clips_{e['vod_id']}", disabled=e["clip_count"] == 0):
                        delete_vod_clips(e["vod_id"])
                        clear_session_if_current(e["vod_id"])
                        st.rerun()
                    if bcol2.button("Supprimer le chat", key=f"del_chat_{e['vod_id']}", disabled=not e["has_chat"]):
                        delete_vod_chat(e["vod_id"])
                        clear_session_if_current(e["vod_id"])
                        st.rerun()
                    if bcol3.button("Tout supprimer", key=f"del_all_{e['vod_id']}", type="primary"):
                        delete_vod_all(e["vod_id"])
                        clear_session_if_current(e["vod_id"])
                        st.rerun()
