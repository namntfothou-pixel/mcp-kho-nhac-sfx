#!/usr/bin/env python3
"""MCP server: Kho nhac & SFX mien phi.

Tim kiem va tai nhac nen / hieu ung am thanh (SFX) mien phi tu cac nguon
mo (Jamendo, Freesound, Wikimedia...) thong qua Openverse API.
Khong can API key. Mac dinh chi tra ve ban CC0 (public domain) de dung
thoai mai cho moi muc dich ma khong can ghi nguon.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unicodedata
import urllib.parse
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

# --- Nguon bo sung (tuy chon, cau hinh qua bien moi truong) ---
# Freesound: key mien phi tai https://freesound.org/apiv2/apply
# Jamendo: client_id mien phi tai https://developer.jamendo.com/v3.0
# Luu y: MCP client chi ke thua it bien moi truong, nen khai bao trong config:
#   "env": {"FREESOUND_API_KEY": "...", "JAMENDO_CLIENT_ID": "..."}
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "").strip()
JAMENDO_CLIENT_ID = os.environ.get("JAMENDO_CLIENT_ID", "").strip()

mcp = FastMCP("kho-nhac-sfx")

API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "kho-nhac-sfx-mcp/1.0 (+local)"}
FIELDS = "id,title,creator,url,preview_url,duration,license,provider,foreign_landing_url,tags"

# The loai goi y: ten tieng Viet -> tu khoa tim kiem tieng Anh (Freesound/Jamendo dung tag tieng Anh)
MUSIC_GENRES = {
    "ambient": "ambient background music",
    "piano": "piano music",
    "lo-fi": "lofi chill beats",
    "electronic": "electronic dance music",
    "cinematic": "cinematic epic music",
    "vui ve / upbeat": "upbeat happy background",
    "jazz": "jazz music",
    "acoustic guitar": "acoustic guitar",
    "rock": "rock music guitar",
    "co dien": "classical orchestra",
    "hip-hop beat": "hip hop beat instrumental",
    "nhac phim / trailer": "epic trailer music",
}

SFX_CATEGORIES = {
    "vo tay": "applause clapping",
    "reo ho dam dong": "crowd cheering",
    "tieng mua": "rain falling",
    "sam set": "thunder storm",
    "chim hot": "birds chirping",
    "song bien": "ocean waves",
    "gio thoi": "wind blowing",
    "buoc chan": "footsteps",
    "whoosh": "whoosh swoosh",
    "tieng chuong": "bell chime",
    "tieng cuoi": "people laughing",
    "vu no": "explosion",
    "click chuot / UI": "mouse click ui",
    "tich tac dong ho": "clock ticking",
    "coi xe": "car horn",
    "tieng buoc nuoc": "water splash",
}


# Cam xuc tieng Viet -> tu khoa nhac tieng Anh (kiem tra theo thu tu, cai cu the truoc)
CAM_XUC_NHAC = [
    (["kinh di", "ma quai", "rung ron", "horror", "dang so"], "dark horror ambient"),
    (["huyen bi", "bi an", "mysterious", "bi mat"], "mysterious dark ambient"),
    (["cang thang", "hoi hop", "gay can", "suspense", "nghet tho"], "tense suspense cinematic"),
    (["hanh dong", "duoi bat", "action"], "action intense cinematic"),
    (["hung trang", "su thi", "hoanh trang", "epic", "vi dai"], "epic cinematic orchestral"),
    (["chien thang", "victory", "thanh cong", "dang quang"], "victory uplifting epic"),
    (["hai huoc", "funny", "buon cuoi", "hai", "vui nhon"], "funny quirky comedic"),
    (["vui ve", "hanh phuc", "tuoi vui", "happy", "vui tuoi", "lac quan"], "upbeat happy background"),
    (["lang man", "romantic", "tinh yeu", "ngot ngao"], "romantic soft piano"),
    (["buon", "sau lang", "melancholic", "tiec thuong", "chia tay", "don doc"], "sad melancholic piano"),
    (["cam dong", "xuc dong", "truyen cam hung", "inspiring", "emotional", "nuoc mat"], "emotional inspiring cinematic"),
    (["binh yen", "thu gian", "nhe nhang", "calm", "nhe nhom", "thanh binh"], "calm ambient relaxing"),
    (["nang dong", "the thao", "nang luong", "energetic", "tap luyen", "gym"], "energetic upbeat motivational"),
    (["sang trong", "luxury", "cao cap", "dang cap"], "elegant luxury background"),
    (["le hoi", "an mung", "party", "lien hoan"], "celebration party upbeat"),
    (["dam cuoi", "wedding"], "wedding romantic elegant"),
    (["giang sinh", "christmas", "noel"], "christmas festive"),
    (["dem", "night", "ban dem"], "calm night ambient"),
    (["du lich", "travel", "kham pha", "phieu luu"], "upbeat travel adventure"),
    (["cong nghe", "technology", "hien dai"], "modern tech corporate"),
    (["tu nhien", "thien nhien", "rung", "bien"], "peaceful nature ambient"),
]


def _bo_dau(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn"
    )


def _query_cho_cam_xuc(mo_ta: str, cam_xuc: str | None) -> tuple[str, str]:
    """Tra ve (ten_cam_xuc_nhan_dien, tu_khoa_tim_kiem). Uu tien cam_xuc khai bao truoc mo ta."""

    def _match(text: str) -> tuple[str, str] | None:
        for keywords, query in CAM_XUC_NHAC:
            hit = next((k for k in keywords if k in text), None)
            if hit:
                return hit, query
        return None

    hit = _match(_bo_dau(cam_xuc or ""))
    if hit:
        return hit
    hit = _match(_bo_dau(mo_ta or ""))
    if hit:
        return hit
    # mac dinh: dung mo ta lam tu khoa
    return "tuong thich mo ta", (mo_ta or "background music").strip() or "background music"


def _search(q: str, license_: str, length: str | None, limit: int) -> list[dict]:
    params = {
        "q": q,
        "license": license_,
        "page_size": max(1, min(limit, 50)),
        "fields": FIELDS,
    }
    if length:
        params["length"] = length
    r = requests.get(API, params=params, headers=UA, timeout=25)
    r.raise_for_status()
    data = r.json()
    out = []
    for item in data.get("results", []):
        tags = [t.get("name") for t in (item.get("tags") or []) if t.get("name")][:8]
        out.append(
            {
                "tieu_de": item.get("title"),
                "tac_gia": item.get("creator"),
                "thoi_luong_giay": round((item.get("duration") or 0) / 1000, 1),
                "giay_phep": item.get("license"),
                "nguon": item.get("provider"),
                "link_nghe_tai_preview": item.get("url") or item.get("preview_url"),
                "link_goc": item.get("foreign_landing_url"),
                "tags": tags,
            }
        )
    return out


def _license_note(license_: str) -> str:
    if "cc0" in license_:
        return "CC0 = public domain: dung thoai mai cho moi muc dich, KHONG can ghi nguon."
    if "by" in license_:
        return "CC BY: dung duoc (ca thuong mai) NHUNG phai ghi nguon tac gia."
    return ""


def _unified(tieu_de, tac_gia, thoi_luong_giay, giay_phep, nguon, preview, link_goc, tags=None):
    return {
        "tieu_de": tieu_de, "tac_gia": tac_gia,
        "thoi_luong_giay": round(thoi_luong_giay or 0, 1), "giay_phep": giay_phep,
        "nguon": nguon, "link_nghe_tai_preview": preview, "link_goc": link_goc,
        "tags": tags or [],
    }


def _search_freesound(q: str, cc0_only: bool, length: str | None, limit: int) -> list[dict]:
    """Tim tren Freesound API (can FREESOUND_API_KEY). Preview mp3 tai truc tiep duoc."""
    if not FREESOUND_API_KEY:
        return []
    try:
        dur_map = {"shortest": "[0 TO 30]", "short": "[0 TO 120]",
                   "medium": "[30 TO 300]", "long": "[120 TO *]"}
        params = {"query": q, "token": FREESOUND_API_KEY,
                  "page_size": min(max(limit * 2, 10), 50),
                  "fields": "id,name,previews,duration,license,username,url"}
        if length and length in dur_map:
            params["filter"] = f"duration:{dur_map[length]}"
        r = requests.get("https://freesound.org/apiv2/search/text/", params=params,
                         headers=UA, timeout=25)
        r.raise_for_status()
        out = []
        for it in r.json().get("results", []):
            lic = it.get("license", "")
            code = "cc0" if lic == "Creative Commons 0" else ("by-nc" if "Noncommercial" in lic else "by")
            if cc0_only and code != "cc0":
                continue
            prev = (it.get("previews") or {}).get("preview-hq-mp3")
            if not prev:
                continue
            out.append(_unified(it.get("name"), it.get("username"), it.get("duration"),
                                code, "freesound", prev, it.get("url")))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _search_jamendo(q: str, length: str | None, limit: int) -> list[dict]:
    """Tim nhac tren Jamendo API (can JAMENDO_CLIENT_ID). Chi lay ban cho phep phai sinh
    (loai bo ND); hau het can ghi nguon + mot so ban cam dung thuong mai (NC)."""
    if not JAMENDO_CLIENT_ID:
        return []
    try:
        params = {"client_id": JAMENDO_CLIENT_ID, "format": "json",
                  "limit": min(max(limit, 5), 50), "search": q, "audioformat": "mp32"}
        if length == "long":
            params["durationfrom"] = 120
        elif length == "short":
            params["durationto"] = 120
        r = requests.get("https://api.jamendo.com/v3.0/tracks/", params=params,
                         headers=UA, timeout=25)
        r.raise_for_status()
        out = []
        for t in r.json().get("results", []):
            m = re.search(r"licenses/([a-z0-9\-]+)/", t.get("license_ccurl") or "")
            code = m.group(1) if m else "by"
            if "nd" in code:  # NoDerivatives: khong ghep vao video duoc
                continue
            audio = t.get("audiodownload") or t.get("audio")
            if not audio:
                continue
            tags = [v for v in ((t.get("musicinfo") or {}).get("tags") or {}).values()
                    if isinstance(v, str)][:6]
            out.append(_unified(t.get("name"), t.get("artist_name"), t.get("duration"),
                                code, "jamendo", audio,
                                f"https://www.jamendo.com/track/{t.get('id')}", tags))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _ia_license_code(licenseurl: str) -> str:
    u = (licenseurl or "").lower()
    if "publicdomain/zero" in u or "publicdomain/mark" in u or "publicdomain/" in u:
        return "cc0"
    if "by-nc-sa" in u:
        return "by-nc-sa"
    if "by-nc-nd" in u or "by-nd" in u:
        return "by-nc-nd"
    if "by-nc" in u:
        return "by-nc"
    if "by-sa" in u:
        return "by-sa"
    if "creativecommons.org/licenses/by" in u:
        return "by"
    return ""


def _search_archive_org(q: str, cc0_only: bool, limit: int) -> list[dict]:
    """Tim audio tren Internet Archive (khong can key). Tai truc tiep, khong can dang nhap."""
    try:
        words = " AND ".join(q.split())
        lic = "licenseurl:*publicdomain*" if cc0_only else "licenseurl:*creativecommons*"
        params = {
            "q": f"mediatype:audio AND {words} AND ({lic})",
            "fl[]": ["identifier", "title", "creator", "licenseurl", "duration"],
            "rows": min(max(limit, 3), 8),
            "output": "json",
        }
        r = requests.get("https://archive.org/advancedsearch.php", params=params,
                         headers=UA, timeout=25)
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        out = []
        for d in docs:
            ident = d.get("identifier")
            if not ident:
                continue
            try:
                m = requests.get(f"https://archive.org/metadata/{ident}", headers=UA, timeout=20)
                m.raise_for_status()
                meta = m.json()
            except Exception:
                continue
            files = meta.get("files", [])
            audio, audio_len = None, 0.0
            for ext_group in ((".mp3",), (".ogg", ".oga"), (".wav", ".flac", ".m4a")):
                for f in files:
                    name = f.get("name", "")
                    if name.lower().endswith(ext_group):
                        audio = name
                        try:
                            audio_len = float(f.get("length") or 0)
                        except (TypeError, ValueError):
                            audio_len = 0.0
                        break
                if audio:
                    break
            if not audio:
                continue
            code = _ia_license_code(d.get("licenseurl") or meta.get("metadata", {}).get("licenseurl", ""))
            if cc0_only and code != "cc0":
                continue
            if "nd" in code:
                continue
            md = meta.get("metadata", {})
            try:
                dur = audio_len or float(md.get("duration") or d.get("duration") or 0)
            except (TypeError, ValueError):
                dur = audio_len
            creator = d.get("creator") or md.get("creator") or ""
            if isinstance(creator, list):
                creator = ", ".join(creator[:2])
            out.append(_unified(
                d.get("title") or ident, creator, dur, code or "by", "internet-archive",
                f"https://archive.org/download/{ident}/{urllib.parse.quote(audio)}",
                f"https://archive.org/details/{ident}"))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _search_commons(q: str, cc0_only: bool, limit: int) -> list[dict]:
    """Tim audio truc tiep tren Wikimedia Commons API (khong can key)."""
    try:
        params = {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:audio {q}", "gsrnamespace": 6,
            "gsrlimit": min(max(limit * 2, 6), 20),
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        }
        r = requests.get("https://commons.wikimedia.org/w/api.php", params=params,
                         headers=UA, timeout=25)
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        out = []
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            url = ii.get("url")
            if not url:
                continue
            ext = ii.get("extmetadata") or {}
            lic = ((ext.get("LicenseShortName") or {}).get("value") or "")
            code = "cc0" if ("CC0" in lic or "Public domain" in lic) else (
                "by-sa" if "BY-SA" in lic.upper() else ("by" if "BY" in lic.upper() else ""))
            if cc0_only and code != "cc0":
                continue
            artist = ((ext.get("Artist") or {}).get("value") or "")
            artist = re.sub(r"<[^>]+>", "", artist).strip()[:60]
            out.append(_unified(
                p.get("title", "").replace("File:", "")[:80], artist, 0, code or "by",
                "wikimedia-commons", url,
                "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(p.get("title", ""))))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _search_all(q: str, license_: str, length: str | None, limit: int, loai: str = "nhac") -> list[dict]:
    """Gop ket qua tu nhieu nguon: Openverse, Freesound, Internet Archive,
    Wikimedia Commons (+ Jamendo neu co key va chap nhan CC BY). Loai trung."""
    cc0_only = "by" not in license_
    per_source = [
        _search(q, license_, length, limit),  # Openverse: khong can key
        _search_freesound(q, cc0_only, length, limit),
        _search_archive_org(q, cc0_only, limit),
        _search_commons(q, cc0_only, limit),
    ]
    if not cc0_only and loai == "nhac":
        # Jamendo yeu cau ghi nguon (va mot so ban NC) nen chi dung khi user chap nhan CC BY
        per_source.append(_search_jamendo(q, length, limit))
    # tron vong tron (round-robin) de moi nguon deu co dai dien, dong thoi loai trung
    results, seen, idx = [], set(), 0
    while len(results) < limit:
        added = False
        for items in per_source:
            if idx < len(items):
                u = items[idx].get("link_nghe_tai_preview")
                if u and u not in seen:
                    seen.add(u)
                    results.append(items[idx])
                    added = True
                    if len(results) >= limit:
                        break
        if not added:
            break
        idx += 1
    return results


def _nguon_dang_bat() -> list[str]:
    src = ["openverse (tong hop, khong can key)",
           "internet-archive (khong can key)",
           "wikimedia-commons (khong can key)"]
    if FREESOUND_API_KEY:
        src.append("freesound API (truc tiep, catalog day du hon)")
    if JAMENDO_CLIENT_ID:
        src.append("jamendo API (nhac, can ghi nguon)")
    return src


@mcp.tool()
def tim_nhac(
    tu_khoa: str,
    giay_phep: str = "cc0",
    do_dai: str = "bat-ky",
    so_luong: int = 10,
) -> dict:
    """Tim nhac nen mien phi theo tu khoa hoac the loai (vd: 'lofi chill', 'piano', 'nhac cinematic').

    - tu_khoa: tu khoa tieng Anh cho ket qua tot nhat (vd 'upbeat happy background'); co the dung ten the loai tieng Viet tu list_genres.
    - giay_phep: 'cc0' (mac dinh, dung tu do khong can ghi nguon) hoac 'cc0,by' (them ban CC BY can ghi nguon).
    - do_dai: 'bat-ky' | 'ngan' (<2 phut) | 'dai' (>2 phut).
    Tra ve danh sach ban nhac kem link nghe/tai preview mp3 va link goc.
    """
    length_map = {"ngan": "short", "dai": "long"}
    key = tu_khoa.strip().lower()
    q = MUSIC_GENRES.get(key, tu_khoa)
    results = _search_all(q, giay_phep, length_map.get(do_dai), so_luong, "nhac")
    return {
        "tu_khoa_da_dung": q,
        "luu_y_giay_phep": _license_note(giay_phep),
        "nguon_dang_dung": _nguon_dang_bat(),
        "so_ket_qua": len(results),
        "ket_qua": results,
    }


@mcp.tool()
def tim_sfx(
    tu_khoa: str,
    thoi_luong_toi_da_giay: int = 30,
    so_luong: int = 10,
) -> dict:
    """Tim hieu ung am thanh (SFX) mien phi: tieng vo tay, tieng mua, whoosh, tieng no...

    - tu_khoa: vd 'applause', 'rain', 'thunder', 'whoosh'; co the dung ten tieng Viet tu list_genres.
    - thoi_luong_toi_da_giay: loc hieu ung ngan (<=30s) hoac dai hon (<=120s).
    Tra ve danh sach SFX kem link nghe/tai preview mp3 va link goc. Mac dinh CC0, dung tu do.
    """
    key = tu_khoa.strip().lower()
    q = SFX_CATEGORIES.get(key, tu_khoa)
    length = "shortest" if thoi_luong_toi_da_giay <= 30 else "short"
    results = _search_all(q, "cc0", length, so_luong, "sfx")
    return {
        "tu_khoa_da_dung": q,
        "luu_y_giay_phep": _license_note("cc0"),
        "nguon_dang_dung": _nguon_dang_bat(),
        "so_ket_qua": len(results),
        "ket_qua": results,
    }


@mcp.tool()
def list_the_loai(loai: str = "tat-ca") -> dict:
    """Liet ke cac the loai nhac va nhom SFX co san de tim kiem (ten tieng Viet kem tu khoa tieng Anh)."""
    loai = loai.strip().lower()
    out: dict = {}
    if loai in ("tat-ca", "nhac"):
        out["nhac"] = MUSIC_GENRES
    if loai in ("tat-ca", "sfx"):
        out["sfx"] = SFX_CATEGORIES
    return out


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\s\-.]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", "_", name)
    return (name or "track")[:80]


def _download_one(link_preview: str, ten_file: str, dest_dir: Path) -> dict:
    fname = _safe_filename(ten_file)
    if not fname.lower().endswith(".mp3"):
        fname += ".mp3"
    dest = dest_dir / fname
    i = 1
    while dest.exists():
        dest = dest_dir / f"{fname[:-4]}-{i}.mp3"
        i += 1
    r = requests.get(link_preview, headers=UA, timeout=60, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    return {"ten_file": dest.name, "da_luu": str(dest), "dung_luong_kb": dest.stat().st_size // 1024}


@mcp.tool()
def tai_xuong(
    link_preview: str,
    ten_file: str,
    thu_muc: str = "kho-nhac-sfx",
) -> dict:
    """Tai 1 file mp3 preview ve may tinh cua ban vao ~/Downloads/<thu_muc>/.

    - link_preview: lay tu 'link_nghe_tai_preview' trong ket qua tim kiem.
    - ten_file: ten file muon luu (vd 'nhac-lofi-hoc-bai'); tu dong them .mp3.
    Luu y: day la ban preview chat luong tot (mp3). Muon ban goc chat luong cao nhat,
    mo 'link_goc' tren trinh duyet (co the can tai khoan Freesound mien phi).
    Can tai nhieu bai mot luc thi dung tool tai_nhieu_bai.
    """
    dest_dir = Path.home() / "Downloads" / _safe_filename(thu_muc)
    dest_dir.mkdir(parents=True, exist_ok=True)
    return _download_one(link_preview, ten_file, dest_dir)


@mcp.tool()
def tai_nhieu_bai(
    danh_sach: list,
    thu_muc: str = "kho-nhac-sfx",
) -> dict:
    """Tai NHIEU file mp3 mot luc ve ~/Downloads/<thu_muc>/.

    - danh_sach: list cac {"link_preview": ..., "ten_file": ...}.
      link_preview lay tu 'link_nghe_tai_preview' trong ket qua cua tim_nhac/tim_sfx
      hoac lap_ke_hoach_nhac_video (chap nhan ca hai key 'link_preview' va
      'link_nghe_tai_preview').
    Tra ve trang thai tung file (thanh cong / loi) de biet bai nao can tai lai.
    """
    dest_dir = Path.home() / "Downloads" / _safe_filename(thu_muc)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ket_qua = []
    for item in danh_sach:
        try:
            link = item.get("link_preview") or item.get("link_nghe_tai_preview")
            if not link:
                raise ValueError("thieu 'link_preview'/'link_nghe_tai_preview'")
            ket_qua.append({"trang_thai": "ok", **_download_one(link, item.get("ten_file", "track"), dest_dir)})
        except Exception as e:  # noqa: BLE001 - bao loi tung file, khong dung ca loat
            ket_qua.append({"trang_thai": "loi", "ten_file": item.get("ten_file"), "loi": str(e)[:200]})
    ok = sum(1 for k in ket_qua if k["trang_thai"] == "ok")
    return {"tong": len(ket_qua), "thanh_cong": ok, "that_bai": len(ket_qua) - ok, "chi_tiet": ket_qua}


@mcp.tool()
def lap_ke_hoach_nhac_video(
    cac_canh: list,
    giay_phep: str = "cc0",
    so_luong_moi_canh: int = 3,
) -> dict:
    """Lap ke hoach nhac cho video co NHIEU canh voi cam xuc khac nhau.

    - cac_canh: list cac canh, moi canh la {"ten_canh": "Mo dau", "mo_ta": "...","cam_xuc": "vui ve", "thoi_luong_giay": 45}.
      "cam_xuc" go tieng Viet tu nhien (vd: vui ve, buon, hoi hop, hung trang, lang man, thu gian...);
      neu bo trong, tool tu doan cam xuc tu "mo_ta". "thoi_luong_giay" giup uu tien ban nhac du dai cho canh.
    - giay_phep: 'cc0' (mac dinh, khong can ghi nguon) hoac 'cc0,by'.
    - so_luong_moi_canh: so ban nhac goi y cho moi canh (1-5).

    Tra ve tung canh kem cam xuc nhan dien va 2-3 ban nhac phu hop (uu tien ban du dai
    hon thoi luong canh). Dung link_nghe_tai_preview de nghe thu, roi dung tai_nhieu_bai
    de tai tat ca cac ban da chon mot luc.
    """
    ke_hoach = []
    for canh in cac_canh:
        ten = canh.get("ten_canh", "Canh")
        mo_ta = canh.get("mo_ta", "")
        cam_xuc = canh.get("cam_xuc")
        thoi_luong = canh.get("thoi_luong_giay")
        ten_cx, query = _query_cho_cam_xuc(mo_ta, cam_xuc)
        if thoi_luong and thoi_luong >= 120:
            length: str | None = "long"
        elif thoi_luong and thoi_luong < 120:
            length = "short"
        else:
            length = None
        n = max(1, min(so_luong_moi_canh, 5))
        goi_y = _search_all(query, giay_phep, length, n, "nhac")
        if not goi_y and length:
            goi_y = _search_all(query, giay_phep, None, n, "nhac")  # bo loc do dai
        if not goi_y:
            gon = " ".join(query.split()[:2])  # rut gon tu khoa
            if gon != query:
                goi_y = _search_all(gon, giay_phep, None, n, "nhac")
        # uu tien ban nhac dai hon (hoac bang) thoi luong canh
        if thoi_luong:
            goi_y.sort(key=lambda t: (t["thoi_luong_giay"] < thoi_luong, -t["thoi_luong_giay"]))
        ke_hoach.append(
            {
                "ten_canh": ten,
                "cam_xuc_nhan_dien": ten_cx,
                "tu_khoa_da_dung": query,
                "thoi_luong_canh_giay": thoi_luong,
                "goi_y_nhac": goi_y,
            }
        )
    return {
        "so_canh": len(ke_hoach),
        "luu_y_giay_phep": _license_note(giay_phep),
        "huong_dan": "Chon 1 ban cho moi canh (uu tien ban co thoi luong >= thoi luong canh), roi dung tai_nhieu_bai de tai tat ca mot luc.",
        "ke_hoach": ke_hoach,
    }


def _ffmpeg_paths():
    return shutil.which("ffmpeg"), shutil.which("ffprobe")


def _video_info(video: Path) -> tuple[float | None, bool]:
    """Tra ve (thoi_luong_giay, co_track_audio)."""
    _, fp = _ffmpeg_paths()
    dur, has_audio = None, False
    if fp:
        try:
            out = subprocess.run(
                [fp, "-v", "error", "-show_entries", "format=duration",
                 "-show_entries", "stream=codec_type", "-of", "json", str(video)],
                capture_output=True, text=True, timeout=30,
            )
            info = json.loads(out.stdout or "{}")
            dur = float(info.get("format", {}).get("duration") or 0) or None
            has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        except Exception:
            pass
    return dur, has_audio


def _ghep_am_thanh(segments: list[dict], video: Path, output: Path, giu_tieng_goc: bool = True) -> Path:
    """Ghep cac doan am thanh vao video bang ffmpeg.
    segments: [{"audio": Path, "bat_dau": giay, "ket_thuc": giay, "am_luong": 0-1, "lap_lai": bool}]
    """
    ff, _ = _ffmpeg_paths()
    if not ff:
        raise RuntimeError(
            "Chua cai ffmpeg tren may. Cai dat: macOS `brew install ffmpeg`, "
            "Ubuntu `sudo apt install ffmpeg`, Windows: tai tu ffmpeg.org va them vao PATH."
        )
    cmd = [ff, "-y", "-i", str(video)]
    for s in segments:
        cmd += ["-i", str(s["audio"])]
    fc = []
    for i, s in enumerate(segments, start=1):
        start_ms = int(s["bat_dau"] * 1000)
        dur = max(0.1, s["ket_thuc"] - s["bat_dau"])
        filters = []
        if s.get("lap_lai"):
            filters.append("aloop=loop=-1:size=2147483647")
        filters.append(f"atrim=duration={dur:.3f}")
        filters.append("asetpts=PTS-STARTPTS")
        if dur > 2 and s.get("lap_lai"):
            filters.append("afade=t=in:st=0:d=1")
            filters.append(f"afade=t=out:st={dur - 1:.3f}:d=1")
        filters.append(f"adelay={start_ms}|{start_ms}")
        filters.append(f"volume={s.get('am_luong', 1.0)}")
        fc.append(f"[{i}:a]" + ",".join(filters) + f"[m{i}]")
    ins = "".join(f"[m{i}]" for i in range(1, len(segments) + 1))
    fc.append(f"{ins}amix=inputs={len(segments)}:normalize=0[mix]")
    _, has_audio = _video_info(video)
    if has_audio and giu_tieng_goc:
        fc.append("[0:a][mix]amix=inputs=2:normalize=0[aout]")
    else:
        fc.append("[mix]anull[aout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg loi: " + (r.stderr or "")[-600:])
    return output


def _tim_ban_nhac_cc0(mo_ta: str, cam_xuc: str | None, thoi_luong: float | None, n: int = 3) -> list[dict]:
    ten_cx, query = _query_cho_cam_xuc(mo_ta, cam_xuc)
    length = "long" if thoi_luong and thoi_luong >= 120 else ("short" if thoi_luong else None)
    goi_y = _search_all(query, "cc0", length, n, "nhac")
    if not goi_y and length:
        goi_y = _search_all(query, "cc0", None, n, "nhac")
    if not goi_y:
        gon = " ".join(query.split()[:2])
        if gon != query:
            goi_y = _search_all(gon, "cc0", None, n, "nhac")
    return goi_y


def _tim_sfx_cc0(tu_khoa: str, n: int = 3) -> tuple[str, list[dict]]:
    key = _bo_dau(tu_khoa.strip())
    q = next((v for k, v in SFX_CATEGORIES.items() if _bo_dau(k) == key), tu_khoa)
    goi_y = _search_all(q, "cc0", "shortest", n, "sfx")
    if not goi_y:
        goi_y = _search_all(q, "cc0", None, n, "sfx")
    return q, goi_y


@mcp.tool()
def tim_them_tren_pixabay(tu_khoa: str) -> dict:
    """Tra ve link duyet tay tren Pixabay Music & SFX theo tu khoa.

    Giai thich: Pixabay KHONG co public API cho nhac/SFX (chi co API anh/video),
    trang web lai chan bot + yeu cau dang nhap moi tai duoc file, nen khong the dua
    vao tim kiem tu dong nhu cac nguon API. Tool nay giup ban mo nhanh trang tim
    kiem Pixabay de nghe thu va tai tay (mien phi, giay phep Pixabay Content License
    - dung duoc thuong mai, khong can ghi nguon).
    """
    q = urllib.parse.quote_plus(tu_khoa.strip())
    return {
        "luu_y": "Pixabay khong co API nhac/SFX nen chi duyet/tai tay duoc. Can dang nhap tai khoan mien phi de tai file.",
        "nhac": f"https://pixabay.com/music/search/{q}/",
        "sfx": f"https://pixabay.com/sound-effects/search/{q}/",
    }


@mcp.tool()
def tu_dong_ghep_am_thanh(
    video_path: str,
    cac_canh: list,
    am_luong_nhac: float = 0.4,
    am_luong_sfx: float = 0.9,
    giu_tieng_goc: bool = True,
    output_path: str | None = None,
    thu_muc_tai: str = "kho-nhac-sfx",
) -> dict:
    """TU DONG HOAN CHINH: tim nhac nen + SFX (CHI ban CC0 - khong can ghi nguon),
    tai ve va ghep vao video theo tung canh voi cam xuc khac nhau.

    - video_path: duong dan file video tren may ban.
    - cac_canh: list cac canh, moi canh: {"ten_canh": "Mo dau", "mo_ta": "...",
      "cam_xuc": "vui ve" (tieng Viet tu nhien; de trong + mo_ta trong = bo qua nhac nen),
      "bat_dau_giay": 0, "ket_thuc_giay": 30 (hoac chi "thoi_luong_giay" de xep noi tiep),
      "sfx": ["vo tay", {"tu_khoa": "sam set", "lech_giay": 2}]}.
      SFX duoc dat vao dau canh (cong lech_giay), chi phat 1 lan, khong lap lai.
    - am_luong_nhac (0-1): do to nhac nen; am_luong_sfx (0-1): do to SFX.
    - giu_tieng_goc: True = giu tieng goc cua video, tron nhac/SFX ben duoi.
    - output_path: duong dan file xuat; bo trong = tu dat ten <video>_ghep-am-thanh.mp4.
    - Yeu cau: may da cai ffmpeg. Tat ca nhac/SFX deu la CC0 (public domain) nen
      video xuat ra DANG THOAI MAI ma khong can ghi nguon.
    """
    ff, _ = _ffmpeg_paths()
    if not ff:
        return {"trang_thai": "loi",
                "loi": "Chua cai ffmpeg. macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg | Windows: ffmpeg.org"}
    video = Path(video_path).expanduser()
    if not video.is_file():
        return {"trang_thai": "loi", "loi": f"Khong tim thay file video: {video_path}"}

    dest_dir = Path.home() / "Downloads" / _safe_filename(thu_muc_tai)
    dest_dir.mkdir(parents=True, exist_ok=True)
    vdur, _ = _video_info(video)

    # 1) Giai quyet moc thoi gian cac canh
    scenes, cursor = [], 0.0
    for canh in cac_canh:
        start = float(canh.get("bat_dau_giay", cursor))
        if canh.get("ket_thuc_giay") is not None:
            end = float(canh["ket_thuc_giay"])
        else:
            end = start + float(canh.get("thoi_luong_giay", 30))
        if vdur:
            end = min(end, vdur)
        if end <= start:
            continue
        scenes.append({**canh, "bat_dau": start, "ket_thuc": end})
        cursor = end
    if not scenes:
        return {"trang_thai": "loi", "loi": "Khong co canh hop le (kiem tra moc thoi gian)."}

    # 2) Tim + tai nhac/SFX CC0 cho tung canh
    segments, chi_tiet = [], []
    for canh in scenes:
        ten = canh.get("ten_canh", "Canh")
        mo_ta = canh.get("mo_ta", "")
        cam_xuc = canh.get("cam_xuc")
        dur = canh["ket_thuc"] - canh["bat_dau"]
        info = {"ten_canh": ten, "bat_dau_giay": canh["bat_dau"], "ket_thuc_giay": canh["ket_thuc"]}

        if mo_ta or cam_xuc:
            goi_y = _tim_ban_nhac_cc0(mo_ta, cam_xuc, dur)
            if not goi_y:
                return {"trang_thai": "loi", "loi": f"Khong tim duoc nhac CC0 cho canh '{ten}'."}
            chon = goi_y[0]
            try:
                dl = _download_one(chon["link_nghe_tai_preview"],
                                   f'{_safe_filename(ten)}-nhac-nen', dest_dir)
            except Exception as e:
                return {"trang_thai": "loi", "loi": f"Tai nhac cho canh '{ten}' that bai: {str(e)[:150]}"}
            segments.append({"audio": Path(dl["da_luu"]), "bat_dau": canh["bat_dau"],
                             "ket_thuc": canh["ket_thuc"], "am_luong": am_luong_nhac, "lap_lai": True})
            info["nhac"] = {"tieu_de": chon["tieu_de"], "tac_gia": chon["tac_gia"],
                            "giay_phep": chon["giay_phep"], "file": dl["da_luu"]}

        sfx_list = []
        for item in canh.get("sfx", []) or []:
            tk = item["tu_khoa"] if isinstance(item, dict) else str(item)
            lech = float(item.get("lech_giay", 0)) if isinstance(item, dict) else 0.0
            q, goi_y = _tim_sfx_cc0(tk)
            if not goi_y:
                sfx_list.append({"tu_khoa": tk, "trang_thai": "khong tim thay"})
                continue
            chon = goi_y[0]
            try:
                dl = _download_one(chon["link_nghe_tai_preview"],
                                   f'{_safe_filename(ten)}-sfx-{_safe_filename(tk)}', dest_dir)
            except Exception as e:
                sfx_list.append({"tu_khoa": tk, "trang_thai": f"tai loi: {str(e)[:100]}"})
                continue
            s_start = canh["bat_dau"] + lech
            s_end = s_start + chon["thoi_luong_giay"] + 1
            if vdur:
                s_end = min(s_end, vdur)
            segments.append({"audio": Path(dl["da_luu"]), "bat_dau": s_start,
                             "ket_thuc": s_end, "am_luong": am_luong_sfx, "lap_lai": False})
            sfx_list.append({"tu_khoa": tk, "tieu_de": chon["tieu_de"],
                             "dat_tai_giay": round(s_start, 1), "file": dl["da_luu"]})
        if sfx_list:
            info["sfx"] = sfx_list
        chi_tiet.append(info)

    if not segments:
        return {"trang_thai": "loi", "loi": "Khong co nhac/SFX nao duoc chon."}

    # 3) Ghep vao video
    out = Path(output_path).expanduser() if output_path else video.parent / f"{video.stem}_ghep-am-thanh.mp4"
    try:
        _ghep_am_thanh(segments, video, out, giu_tieng_goc)
    except Exception as e:
        return {"trang_thai": "loi", "loi": str(e)[:400]}

    return {
        "trang_thai": "ok",
        "video_dau_ra": str(out),
        "luu_y": "Tat ca nhac/SFX deu la CC0 (public domain) - dang video thoai mai, KHONG can ghi nguon.",
        "cac_canh": chi_tiet,
    }


# ---------------------------------------------------------------------------
# Tu dong nhan dien noi dung video (khong can mo ta canh bang tay)
# ---------------------------------------------------------------------------
# Nguong phan loai (co the tinh chinh):
NGUONG_TOI = 70          # do sang trung binh < nay => canh toi
NGUONG_SANG = 150        # do sang trung binh > nay => canh sang
NGUONG_CHUYEN_DONG_THAP = 8    # do chuyen dong trung binh < nay => tinh
NGUONG_CHUYEN_DONG_CAO = 25    # > nay => chuyen dong manh
NGUONG_NHO = -35         # am luong (dB) < nay => yen tinh
NGUONG_TO = -20          # > nay => on ao


def _phat_hien_canh(video: Path) -> list[float]:
    """Phat hien cat canh: trich frame nho (fps=2), so sanh do khac nhau giua cac
    frame lien tiep bang Python thuan. Tra ve cac moc bien (giay) gom 0 va cuoi video."""
    import statistics
    ff, _ = _ffmpeg_paths()
    FPS, W, H = 2, 64, 36
    r = subprocess.run(
        [ff, "-v", "error", "-i", str(video), "-vf", f"fps={FPS},scale={W}:{H}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=300,
    )
    raw, fs = r.stdout, W * H
    n = len(raw) // fs
    if n < 2:
        vdur, _ = _video_info(video)
        return [0.0, vdur or 0.0]
    frames = [raw[i * fs:(i + 1) * fs] for i in range(n)]
    diffs = [sum(abs(a - b) for a, b in zip(frames[i], frames[i + 1])) / fs
             for i in range(n - 1)]
    nguong = max(30.0, 3.0 * (statistics.median(diffs) or 0.0))
    cuts = [(i + 1) / FPS for i, d in enumerate(diffs) if d > nguong]
    vdur, _ = _video_info(video)
    bounds = sorted({0.0, *cuts, vdur or 0.0})
    # gop canh qua ngan (<3s)
    merged = [bounds[0]]
    for b in bounds[1:]:
        if b - merged[-1] < 3 and len(merged) > 1:
            merged[-1] = b
        else:
            merged.append(b)
    return merged


def _phan_tich_khung_hinh(video: Path, start: float, end: float) -> dict:
    """Lay vai frame giua canh, tinh do sang / bao hoa / chuyen dong (thuan Python)."""
    ff, _ = _ffmpeg_paths()
    mid = (start + end) / 2
    ss = max(0.0, mid - 1.0)
    r = subprocess.run(
        [ff, "-v", "error", "-ss", f"{ss:.2f}", "-t", "2", "-i", str(video),
         "-vf", "fps=2,scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=60,
    )
    raw = r.stdout
    W, H, frames = 64, 36, []
    fsize = W * H * 3
    for i in range(len(raw) // fsize):
        px = raw[i * fsize:(i + 1) * fsize]
        bright = [0.299 * px[j] + 0.587 * px[j + 1] + 0.114 * px[j + 2]
                  for j in range(0, fsize, 3)]
        sat = [max(px[j], px[j + 1], px[j + 2]) - min(px[j], px[j + 1], px[j + 2])
               for j in range(0, fsize, 3)]
        frames.append((sum(bright) / len(bright), sum(sat) / len(sat), bright))
    if not frames:
        return {"do_sang": 128.0, "chuyen_dong": 0.0}
    do_sang = sum(f[0] for f in frames) / len(frames)
    motion = 0.0
    if len(frames) > 1:
        diffs = []
        for a, b in zip(frames, frames[1:]):
            diffs.append(sum(abs(x - y) for x, y in zip(a[2], b[2])) / len(a[2]))
        motion = sum(diffs) / len(diffs)
    return {"do_sang": round(do_sang, 1), "chuyen_dong": round(motion, 1)}


def _thoi_luong_audio(video: Path) -> float | None:
    """Thoi luong track audio (giay); None neu khong co."""
    _, fp = _ffmpeg_paths()
    if not fp:
        return None
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=duration", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        return float((out.stdout or "").strip().splitlines()[0])
    except Exception:
        return None


def _am_luong_doan(video: Path, start: float, end: float, audio_dur: float | None) -> float:
    """Am luong trung binh (dB) cua doan; ngoai vung co audio => -91 (yen tinh)."""
    if audio_dur is not None and start + 0.5 >= audio_dur:
        return -91.0
    ff, _ = _ffmpeg_paths()
    dur = max(0.5, min(4.0, end - start))
    r = subprocess.run(
        [ff, "-v", "info", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(video),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    m = re.search(r"mean_volume:\s*(-?[0-9.]+|-\s*inf)\s*dB", r.stderr)
    if not m:
        return -91.0
    val = m.group(1).replace(" ", "")
    return -91.0 if "inf" in val else float(val)


def _chuan_hoa(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    rng = hi - lo
    if rng < 1e-6:
        return [0.5] * len(values)
    return [(v - lo) / rng for v in values]


def _doan_mood(sang: str, dong: str, tieng: str) -> str:
    """Map nhan (toi/sang/vua, thap/cao/vua, nho/to/vua) -> cam xuc tieng Viet."""
    if dong == "cao" and tieng == "to":
        return "hanh dong nang dong"
    if dong == "cao":
        return "nang dong vui ve"
    if tieng == "to":
        return "hoi hop cang thang"
    if sang == "toi":
        return "bi an tram lang"
    if sang == "sang" and dong == "thap":
        return "binh yen thu gian"
    if dong == "thap" and tieng == "nho":
        return "lang man nhe nhang"
    return "nhe nhang thu gian"


def _phan_tich_video(video: Path, so_canh_toi_da: int = 8) -> list[dict]:
    """Phat hien canh + phan tich mood tung canh (chuan hoa tuong doi theo video)."""
    bounds = _phat_hien_canh(video)
    scenes = [{"bat_dau": bounds[i], "ket_thuc": bounds[i + 1]} for i in range(len(bounds) - 1)]
    while len(scenes) > so_canh_toi_da:
        idx = min(range(len(scenes)), key=lambda i: scenes[i]["ket_thuc"] - scenes[i]["bat_dau"])
        if idx == len(scenes) - 1:
            scenes[idx - 1]["ket_thuc"] = scenes[idx]["ket_thuc"]
        else:
            scenes[idx + 1]["bat_dau"] = scenes[idx]["bat_dau"]
        scenes.pop(idx)
    audio_dur = _thoi_luong_audio(video)
    feats = []
    for sc in scenes:
        f = _phan_tich_khung_hinh(video, sc["bat_dau"], sc["ket_thuc"])
        f["am_luong_db"] = round(_am_luong_doan(video, sc["bat_dau"], sc["ket_thuc"], audio_dur), 1)
        feats.append(f)
    # chuan hoa tuong doi: video nao cung phan biet duoc canh "nang" nhat / "tinh" nhat
    n_sang = _chuan_hoa([f["do_sang"] for f in feats])
    n_dong = _chuan_hoa([f["chuyen_dong"] for f in feats])
    n_tieng = _chuan_hoa([f["am_luong_db"] for f in feats])
    for i, (sc, f) in enumerate(zip(scenes, feats)):
        sang = "toi" if n_sang[i] < 0.35 else ("sang" if n_sang[i] > 0.65 else "vua")
        dong = ("cao" if (n_dong[i] > 0.6 and f["chuyen_dong"] > 2.0)
                else ("thap" if n_dong[i] < 0.35 else "vua"))
        tieng = ("to" if (n_tieng[i] > 0.6 and f["am_luong_db"] > -38.0)
                 else ("nho" if (n_tieng[i] < 0.35 or f["am_luong_db"] <= -45.0) else "vua"))
        sc["ten_canh"] = f"Canh {i + 1}"
        sc["dac_trung"] = f
        sc["nhan"] = {"sang": sang, "dong": dong, "tieng": tieng}
        sc["mood"] = _doan_mood(sang, dong, tieng)
    return scenes


@mcp.tool()
def tu_dong_nhan_dien_va_ghep(
    video_path: str,
    so_canh_toi_da: int = 8,
    am_luong_nhac: float = 0.35,
    am_luong_sfx: float = 0.5,
    them_sfx_tu_dong: bool = True,
    giu_tieng_goc: bool = True,
    che_do: str = "xem-truoc",
    output_path: str | None = None,
    thu_muc_tai: str = "kho-nhac-sfx",
) -> dict:
    """TU DONG HOAN TOAN - khong can mo ta canh: tool tu "xem" video bang ffmpeg
    (phat hien cat canh, do sang, chuyen dong, am luong) de doan cam xuc tung canh,
    roi tu tim nhac nen + SFX (CHI ban CC0 - khong can ghi nguon), tai ve va ghep vao video.

    - video_path: duong dan file video.
    - so_canh_toi_da: gioi han so canh (mac dinh 8); canh thua se duoc gop lai.
    - them_sfx_tu_dong: True = tu dat tieng whoosh nhe o nhung canh cat manh, chuyen dong cao.
    - che_do: "xem-truoc" = chi phan tich va bao ke hoach (khong tai, khong ghep);
      "thuc-hien" = tai va ghep that ra file video moi.
    - output_path: bo trong = tu dat ten <video>_auto-am-thanh.mp4.
    - Yeu cau: may da cai ffmpeg.
    """
    ff, _ = _ffmpeg_paths()
    if not ff:
        return {"trang_thai": "loi",
                "loi": "Chua cai ffmpeg. macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"}
    video = Path(video_path).expanduser()
    if not video.is_file():
        return {"trang_thai": "loi", "loi": f"Khong tim thay file video: {video_path}"}

    scenes = _phan_tich_video(video, so_canh_toi_da)
    if not scenes:
        return {"trang_thai": "loi", "loi": "Khong phan tich duoc video."}

    # Lap ke hoach nhac/SFX cho tung canh da nhan dien
    for sc in scenes:
        dur = sc["ket_thuc"] - sc["bat_dau"]
        ten_cx, query = _query_cho_cam_xuc("", sc["mood"])
        sc["cam_xuc_nhan_dien"] = ten_cx
        sc["tu_khoa_nhac"] = query
        if them_sfx_tu_dong and sc["nhan"]["dong"] == "cao":
            sc["sfx_tu_dong"] = "whoosh"
        else:
            sc.pop("sfx_tu_dong", None)

    if che_do == "xem-truoc":
        return {
            "trang_thai": "xem-truoc",
            "video": str(video),
            "so_canh": len(scenes),
            "huong_dan": "Kiem tra ke hoach duoi day. Neu on, goi lai voi che_do='thuc-hien' de tai va ghep that.",
            "ke_hoach": [
                {"ten_canh": s["ten_canh"],
                 "moc_giay": [round(s["bat_dau"], 1), round(s["ket_thuc"], 1)],
                 "dac_trung": s["dac_trung"], "nhan": s["nhan"], "mood": s["mood"],
                 "nhac_du_kien": s["tu_khoa_nhac"],
                 "sfx_du_kien": s.get("sfx_tu_dong")}
                for s in scenes
            ],
        }

    # Thuc hien: tim + tai + ghep
    dest_dir = Path.home() / "Downloads" / _safe_filename(thu_muc_tai)
    dest_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    for sc in scenes:
        dur = sc["ket_thuc"] - sc["bat_dau"]
        goi_y = _tim_ban_nhac_cc0("", sc["mood"], dur)
        if not goi_y:
            return {"trang_thai": "loi", "loi": f"Khong tim duoc nhac CC0 cho {sc['ten_canh']} (mood: {sc['mood']})."}
        chon = goi_y[0]
        try:
            dl = _download_one(chon["link_nghe_tai_preview"], f'{_safe_filename(sc["ten_canh"])}-auto-nhac', dest_dir)
        except Exception as e:
            return {"trang_thai": "loi", "loi": f"Tai nhac cho {sc['ten_canh']} that bai: {str(e)[:150]}"}
        segments.append({"audio": Path(dl["da_luu"]), "bat_dau": sc["bat_dau"],
                         "ket_thuc": sc["ket_thuc"], "am_luong": am_luong_nhac, "lap_lai": True})
        sc["nhac_da_chon"] = {"tieu_de": chon["tieu_de"], "tac_gia": chon["tac_gia"], "file": dl["da_luu"]}
        if sc.get("sfx_tu_dong"):
            _, sfx_goi_y = _tim_sfx_cc0(sc["sfx_tu_dong"])
            if sfx_goi_y:
                sfx = sfx_goi_y[0]
                try:
                    dl2 = _download_one(sfx["link_nghe_tai_preview"],
                                        f'{_safe_filename(sc["ten_canh"])}-auto-sfx', dest_dir)
                    segments.append({"audio": Path(dl2["da_luu"]), "bat_dau": sc["bat_dau"],
                                     "ket_thuc": sc["bat_dau"] + sfx["thoi_luong_giay"] + 1,
                                     "am_luong": am_luong_sfx, "lap_lai": False})
                    sc["sfx_da_chon"] = {"tieu_de": sfx["tieu_de"], "file": dl2["da_luu"]}
                except Exception:
                    pass

    out = Path(output_path).expanduser() if output_path else video.parent / f"{video.stem}_auto-am-thanh.mp4"
    try:
        _ghep_am_thanh(segments, video, out, giu_tieng_goc)
    except Exception as e:
        return {"trang_thai": "loi", "loi": str(e)[:400]}
    return {
        "trang_thai": "ok",
        "video_dau_ra": str(out),
        "luu_y": "Tat ca nhac/SFX deu la CC0 (public domain) - KHONG can ghi nguon.",
        "cac_canh": [
            {"ten_canh": s["ten_canh"], "moc_giay": [round(s["bat_dau"], 1), round(s["ket_thuc"], 1)],
             "mood": s["mood"], "nhac": s.get("nhac_da_chon", {}).get("tieu_de"),
             "sfx": s.get("sfx_da_chon", {}).get("tieu_de")}
            for s in scenes
        ],
    }


if __name__ == "__main__":
    mcp.run()
