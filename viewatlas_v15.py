"""ViewAtlas V14.1 — bookmarks, multi-format captures, and multilingual UI for Painter 12.

Bookmark data: stored in project.Metadata, same context/key as V3.
Screenshot region, output directory and collage preferences: stored in QSettings per user.

Viewport capture uses Qt's desktop screenshot (QScreen.grabWindow).
To avoid guessing Painter's private viewport QWidget, select the 3D viewport
rectangle once, then save PNGs with one click. Does not render at a higher
resolution, and only captures pixels currently visible on the desktop.
Channel switching is experimental: Painter 12 does not expose a verified public
Python setter for the viewport display channel.
"""

import base64
import json
import math
import os
import re
import traceback
from datetime import datetime

import substance_painter.display as display
import substance_painter.project as project
import substance_painter.ui as ui
try:
    import substance_painter.textureset as textureset
except Exception:
    textureset = None
# Substance Painter <10.1 uses Qt5 (PySide2); 10.1+ uses Qt6 (PySide6).
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import isValid as _shiboken_is_valid
    _QT_MAJOR = 6
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import isValid as _shiboken_is_valid
    _QT_MAJOR = 5
_ACTION_CLASS = QtWidgets.QAction if _QT_MAJOR == 5 else QtGui.QAction
_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'viewatlas_assets')


def _brand_icon():
    file_path = os.path.join(_ASSET_DIR, 'viewatlas.ico')
    if not os.path.isfile(file_path):
        file_path = os.path.join(_ASSET_DIR, 'viewatlas_icon.png')
    return QtGui.QIcon(file_path) if os.path.isfile(file_path) else QtGui.QIcon()


def _brand_mark():
    p = os.path.join(_ASSET_DIR, 'viewatlas_mark.png')
    return QtGui.QPixmap(p) if os.path.isfile(p) else QtGui.QPixmap()


APP_NAME = "ViewAtlas"  # Intentionally not localized and not named after the host app.
BUILD_VERSION = "15.0"

_CONTEXT = "CustomCameraBookmarks_v1"  # Keep V3's saved views.
_KEY = "slots"
_SELECTION_KEY = "batch_selected_v12"
_NUM_SLOTS = 10
_SETTINGS_ORG = "PainterCameraBookmarks"
_SETTINGS_APP = "V4ViewportCapture"  # Keep region/output preferences from V4.

_widget = None
_dock = None
_action = None
_selector = None
_region_preview = None  # v14 persistent, input-transparent outline
_app_state_connected = False

_FORMAT_PREF_ORDER = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'ppm', 'xbm', 'xpm']
_CHANNEL_MODE_ITEMS = [('current','Current viewport'),('material','Material'),('basecolor','BaseColor'),('roughness','Roughness'),('metallic','Metallic'),('normal','Normal')]
_MODE_TRANSLATIONS = {
 'en': ['Current viewport','Material','BaseColor','Roughness','Metallic','Normal'],
 'ko': ['현재 화면','머티리얼','베이스컬러','러프니스','메탈릭','노말'],
 'ja': ['現在の表示','マテリアル','ベースカラー','ラフネス','メタリック','ノーマル'],
 'zh_CN': ['当前视图','材质','基础颜色','粗糙度','金属度','法线'],
 'zh_TW': ['目前視圖','材質','基礎色','粗糙度','金屬度','法線'],
 'es': ['Vista actual','Material','Color base','Rugosidad','Metálico','Normal'],
 'fr': ['Vue actuelle','Matériau','Couleur de base','Rugosité','Métal','Normale'],
 'de': ['Aktuelle Ansicht','Material','Grundfarbe','Rauheit','Metall','Normal'],
 'pt': ['Vista atual','Material','Cor base','Rugosidade','Metálico','Normal'],
 'ru': ['Текущий вид','Материал','Базовый цвет','Шероховатость','Металл','Нормаль'],
 'it': ['Vista corrente','Materiale','Colore base','Rugosità','Metallico','Normale'],
}
_INHERIT_TRANSLATIONS = {
 'en': 'Use global default', 'ko': '전체 설정 사용','ja': '共通設定を使用',
 'zh_CN':'使用全局设置','zh_TW':'使用全域設定','es':'Usar configuración global',
 'fr':'Utiliser le réglage global','de':'Globale Einstellung nutzen',
 'pt':'Usar configuração global','ru':'Глобальные настройки','it':'Usa impostazione globale',
}
_standalone = None



# Locale handling: Painter does not document a dedicated Python getter for its UI language.
# Use the effective Qt widget/application locale, then system locale. Auto falls back to English.
_LANGUAGES = [
    ('auto', 'Auto (App / System)'),
    ('en', 'English'), ('ko', '한국어'), ('ja', '日本語'),
    ('zh_CN', '简体中文'), ('zh_TW', '繁體中文'),
    ('es', 'Español'), ('fr', 'Français'), ('de', 'Deutsch'),
    ('pt', 'Português'), ('ru', 'Русский'), ('it', 'Italiano'),
]
_TRANSLATIONS = {'en': {'auto': 'Auto (App / System)',
        'language': 'Language:',
        'pin': 'Keep visible in Tab full-screen (Always on top)',
        'pin_tip': 'Switch to a separate always-on-top window to try to stay visible when Painter hides '
                   'its interface with Tab.',
        'note': 'Save the current camera angle, then return to it at any time.',
        'slots': 'Camera bookmark slots:',
        'slot_suffix': '',
        'view': 'View {n}',
        'save': 'Save',
        'go': 'Go',
        'refresh': 'Refresh project bookmarks',
        'screenshots': '3D VIEWPORT SCREENSHOTS (PNG)',
        'hint': 'Keep original aspect ratio · Select capture area once, then save PNGs',
        'select_region': '① Select viewport region',
        'screenshot': '② Save PNG screenshot',
        'all_title': 'COMBINE ALL SAVED VIEWS INTO ONE IMAGE',
        'all_desc': 'Capture saved slots in order. Preserve original aspect ratio by default; empty and '
                    'hidden slots are skipped.',
        'layout': 'Layout:',
        'layout_row': 'Single horizontal row (original ratio)',
        'layout_three': '3-column grid',
        'layout_two': '2-column grid',
        'gap': 'Gap:',
        'crop': 'Optional: crop center to a 1:2 portrait strip (OFF by default)',
        'crop_tip': 'OFF preserves each capture at its original ratio. ON crops a centered 1:2 portrait '
                    'strip without stretching.',
        'ratio_hint': 'Preserve actual image pixels (Windows 125/150/200% scaling correction).\n'
                      'Each captured pixel is kept at its original size.',
        'delay': 'View render delay:',
        'batch': '③ Capture and combine all saved views (keep ratio)',
        'batch_tip': 'Capture every visible saved slot and combine it at original pixel size. Portrait '
                     'cropping is optional.',
        'region_unset': 'Capture region: not set (use button ①)',
        'region_set': 'Capture region: {w} × {h} (screen coordinates)',
        'output': 'Save to:',
        'browse': 'Change folder',
        'choose_folder': 'Choose a folder for PNG files',
        'selector_title': 'Select Substance Painter 3D Viewport',
        'selector_help': 'Drag to select ONLY the 3D viewport · Esc to cancel',
        'switching': 'Switching window mode…',
        'project_needed': 'Open a Painter project first. Screenshots may still be taken without a project.',
        'bookmarks_ready': 'Camera bookmarks are ready.',
        'saved': '{name} saved. Remember to save your .spp project.',
        'empty': 'This bookmark is empty.',
        'moved': 'Moved to {name}.',
        'select_instruction': 'Drag a rectangle around the 3D viewport in Painter.',
        'select_success': 'Viewport region selected ({w}×{h}). You can now save a PNG.',
        'select_cancel': 'Region selection cancelled.',
        'taking': 'Capturing screenshot…',
        'saved_png': 'PNG saved: {path}',
        'need_region': 'Select the viewport region first (button ①).',
        'bad_dir': 'The output folder does not exist. Choose another folder.',
        'no_screen': 'Cannot find the screen for this region. Select it again.',
        'outside': 'The capture region is outside the screen or crosses monitors. Select it again.',
        'grab_fail': 'Screen capture failed. Make sure Painter is visible.',
        'png_fail': 'Failed to save PNG: {path}',
        'batch_progress': 'Capturing {count} views… Keep other windows off the Painter viewport.',
        'no_views': 'No saved camera views in the visible slots. Save a bookmark first.',
        'batch_success': 'Combined {count} views. PNG saved: {path}',
        'error': 'Error: {error}',
        'language_auto_tip': 'Auto uses the application Qt locale when available, then the system '
                             'language. Unsupported languages fall back to English.',
        'restore_failed': 'Original camera could not be restored: {error}',
        'no_images': 'No captured images to combine.',
        'image_too_large': 'Choose a smaller viewport capture region and try again.',
        'out_of_memory': 'Not enough memory for the combined image.'},
 'ko': {'auto': '자동 (앱 / 시스템)',
        'language': '언어:',
        'pin': 'Tab 전체화면에서도 창 고정 (항상 위)',
        'pin_tip': '독립된 항상-위 창으로 전환해 Tab으로 Painter UI를 숨겨도 창이 보이도록 시도합니다.',
        'note': '현재 카메라 각도를 저장하고 언제든 그 시점으로 돌아갑니다.',
        'slots': '카메라 저장 슬롯 수:',
        'slot_suffix': '개',
        'view': '뷰 {n}',
        'save': '저장',
        'go': '이동',
        'refresh': '프로젝트 슬롯 새로고침',
        'screenshots': '3D 뷰포트 스크린샷 (PNG)',
        'hint': '원본 비율 유지 · 영역 한 번 지정 후 PNG 저장',
        'select_region': '① 뷰포트 영역 지정',
        'screenshot': '② PNG 스크린샷 저장',
        'all_title': '저장된 뷰 전체를 한 장으로',
        'all_desc': '저장한 슬롯을 순서대로 촬영합니다. 기본은 원본 비율 유지이며 비어 있거나 숨긴 슬롯은 제외합니다.',
        'layout': '배치:',
        'layout_row': '가로 한 줄 (원본 비율)',
        'layout_three': '3열 그리드',
        'layout_two': '2열 그리드',
        'gap': '간격:',
        'crop': '선택: 가운데를 1:2 세로로 자르기 (기본 OFF)',
        'crop_tip': '끄면 원본 비율 유지. 켜면 중앙을 1:2 세로로 자르며 이미지를 늘이지 않습니다.',
        'ratio_hint': '원본 픽셀 유지 (Windows 125/150/200% 배율 보정)\n캡처한 픽셀을 축소하지 않고 연결합니다.',
        'delay': '뷰 렌더 대기:',
        'batch': '③ 저장한 뷰 전체 합치기 (비율 유지)',
        'batch_tip': '표시된 저장 슬롯을 원본 픽셀 크기로 촬영·합칩니다. 세로 크롭은 선택 사항입니다.',
        'region_unset': '캡처 영역: 미설정 (①로 지정)',
        'region_set': '캡처 영역: {w} × {h} (화면 기준)',
        'output': '저장 위치:',
        'browse': '폴더 변경',
        'choose_folder': 'PNG 저장 폴더 선택',
        'selector_title': 'Substance Painter 3D 뷰포트 선택',
        'selector_help': '3D 뷰포트만 드래그해서 선택 · Esc 취소',
        'switching': '창 모드를 전환하는 중…',
        'project_needed': '먼저 프로젝트를 열어 주세요. 스크린샷은 프로젝트 없이도 가능합니다.',
        'bookmarks_ready': '카메라 북마크를 사용할 수 있습니다.',
        'saved': '{name} 저장 완료. .spp 프로젝트도 저장해 주세요.',
        'empty': '이 슬롯은 비어 있습니다.',
        'moved': '{name} 시점으로 이동했습니다.',
        'select_instruction': 'Painter 화면에서 3D 뷰포트만 드래그해 주세요.',
        'select_success': '뷰포트 영역 설정 완료 ({w}×{h}). PNG 저장이 가능합니다.',
        'select_cancel': '영역 지정을 취소했습니다.',
        'taking': '스크린샷 촬영 중…',
        'saved_png': 'PNG 저장 완료: {path}',
        'need_region': '먼저 ① 뷰포트 영역 지정을 눌러 주세요.',
        'bad_dir': '저장 폴더가 없습니다. 다른 폴더를 선택해 주세요.',
        'no_screen': '화면을 찾지 못했습니다. 영역을 다시 지정해 주세요.',
        'outside': '캡처 영역이 화면 밖이거나 여러 모니터에 걸쳐 있습니다. 다시 지정해 주세요.',
        'grab_fail': '화면 캡처에 실패했습니다. Painter가 보이는지 확인해 주세요.',
        'png_fail': 'PNG 저장 실패: {path}',
        'batch_progress': '{count}개 뷰를 촬영 중… Painter 화면을 가리지 마세요.',
        'no_views': '표시된 슬롯에 저장된 뷰가 없습니다. 먼저 저장해 주세요.',
        'batch_success': '{count}개 뷰 합치기 완료. PNG: {path}',
        'error': '오류: {error}',
        'language_auto_tip': '자동: 가능하면 Qt 앱 언어를 사용하고, 이후 시스템 언어를 참고합니다. 미지원 언어는 영어로 표시합니다.',
        'restore_failed': '원래 카메라를 복구하지 못했습니다: {error}',
        'no_images': '합칠 캡처 이미지가 없습니다.',
        'image_too_large': '뷰포트 영역을 더 작게 지정한 뒤 다시 시도해 주세요.',
        'out_of_memory': '합친 이미지의 메모리를 확보하지 못했습니다.'},
 'ja': {'auto': '自動（アプリ / システム）',
        'language': '言語:',
        'pin': 'Tab全画面でも表示（常に手前）',
        'pin_tip': '独立した最前面ウィンドウに切り替え、TabでUIを隠しても表示を維持します。',
        'note': '現在のカメラを保存し、いつでも同じ視点に戻せます。',
        'slots': 'カメラスロット数:',
        'slot_suffix': '個',
        'view': 'ビュー {n}',
        'save': '保存',
        'go': '移動',
        'refresh': 'ブックマークを更新',
        'screenshots': '3Dビューポートのスクリーンショット (PNG)',
        'hint': '元の縦横比を維持 · 範囲を一度指定してPNG保存',
        'select_region': '① ビューポート範囲を指定',
        'screenshot': '② PNGを保存',
        'all_title': '保存したビューを1枚に結合',
        'all_desc': '保存したスロットを順に撮影。既定では元の縦横比を維持し、空や非表示のスロットは除外します。',
        'layout': '配置:',
        'layout_row': '横一列（元の比率）',
        'layout_three': '3列グリッド',
        'layout_two': '2列グリッド',
        'gap': '間隔:',
        'crop': '任意: 中央を縦1:2で切り抜く（既定OFF）',
        'crop_tip': 'OFFは元の比率を維持。ONは中央を縦1:2に切り抜き、引き伸ばしません。',
        'ratio_hint': '画像の実ピクセルを維持（Windows拡大率に対応）\n各ピクセルを縮小せず結合します。',
        'delay': '描画待機:',
        'batch': '③ 保存ビューをまとめて結合',
        'batch_tip': '表示中の保存スロットを元のピクセルサイズで結合します。縦切り抜きは任意です。',
        'region_unset': '撮影範囲: 未設定（①で指定）',
        'region_set': '撮影範囲: {w} × {h}（画面座標）',
        'output': '保存先:',
        'browse': 'フォルダ変更',
        'choose_folder': 'PNG保存先を選択',
        'selector_title': 'Painterの3Dビューポートを選択',
        'selector_help': '3Dビューポートだけドラッグで選択 · Escで取消',
        'switching': 'ウィンドウモードを変更中…',
        'project_needed': '先にプロジェクトを開いてください。スクリーンショットは撮影可能です。',
        'bookmarks_ready': 'カメラブックマークの準備ができました。',
        'saved': '{name} を保存しました。.sppも保存してください。',
        'empty': 'このスロットは空です。',
        'moved': '{name} に移動しました。',
        'select_instruction': 'Painterで3Dビューポートの範囲をドラッグしてください。',
        'select_success': '撮影範囲を設定しました（{w}×{h}）。PNG保存できます。',
        'select_cancel': '範囲選択をキャンセルしました。',
        'taking': 'スクリーンショット撮影中…',
        'saved_png': 'PNG保存完了: {path}',
        'need_region': '先に①で撮影範囲を指定してください。',
        'bad_dir': '保存先がありません。別のフォルダを選んでください。',
        'no_screen': '画面が見つかりません。範囲を再指定してください。',
        'outside': '範囲が画面外または複数モニターにまたがっています。再指定してください。',
        'grab_fail': '撮影失敗。Painterの画面を確認してください。',
        'png_fail': 'PNG保存失敗: {path}',
        'batch_progress': '{count}ビューを撮影中… Painterを隠さないでください。',
        'no_views': '表示中の保存ビューがありません。先に保存してください。',
        'batch_success': '{count}ビューを結合しました: {path}',
        'error': 'エラー: {error}',
        'language_auto_tip': '自動はQtアプリの言語、次にシステム言語を参照します。未対応は英語です。',
        'restore_failed': '元のカメラに戻せませんでした: {error}',
        'no_images': '結合する画像がありません。',
        'image_too_large': '撮影範囲を小さくして再試行してください。',
        'out_of_memory': '結合画像のメモリが不足しています。'},
 'zh_CN': {'auto': '自动（应用 / 系统）',
           'language': '语言：',
           'pin': 'Tab 全屏时保持显示（置顶）',
           'pin_tip': '切换为独立置顶窗口，尝试在按 Tab 隐藏 Painter 界面时继续显示。',
           'note': '保存当前相机视角，随时快速返回。',
           'slots': '相机书签数量：',
           'slot_suffix': '个',
           'view': '视角 {n}',
           'save': '保存',
           'go': '跳转',
           'refresh': '刷新项目书签',
           'screenshots': '3D 视口截图 (PNG)',
           'hint': '保持原始宽高比 · 首次选区，之后一键保存',
           'select_region': '① 选择视口区域',
           'screenshot': '② 保存 PNG 截图',
           'all_title': '将所有已保存视角合并为一张图片',
           'all_desc': '按顺序拍摄已保存视角。默认保持原始比例，跳过空白及隐藏书签。',
           'layout': '排列：',
           'layout_row': '横向单排（原始比例）',
           'layout_three': '三列网格',
           'layout_two': '两列网格',
           'gap': '间距：',
           'crop': '可选：居中裁剪为 1:2 竖幅（默认关闭）',
           'crop_tip': '关闭时保留原始比例；开启时居中裁剪为 1:2，不拉伸。',
           'ratio_hint': '保留原始像素（适配 Windows 125/150/200% 缩放）\n拼接时不缩小截图。',
           'delay': '渲染等待：',
           'batch': '③ 拍摄并合并所有视角（保持比例）',
           'batch_tip': '以原始像素尺寸合并可见书签，竖幅裁剪为可选项。',
           'region_unset': '截图区域：未设置（点击①）',
           'region_set': '截图区域：{w} × {h}（屏幕坐标）',
           'output': '保存到：',
           'browse': '更改文件夹',
           'choose_folder': '选择 PNG 保存文件夹',
           'selector_title': '选择 Painter 3D 视口',
           'selector_help': '拖动选择 3D 视口区域 · Esc 取消',
           'switching': '正在切换窗口模式…',
           'project_needed': '请先打开 Painter 项目。没有项目仍可截图。',
           'bookmarks_ready': '相机书签已就绪。',
           'saved': '已保存 {name}。请记得保存 .spp 项目。',
           'empty': '该书签为空。',
           'moved': '已跳转到 {name}。',
           'select_instruction': '请在 Painter 中拖动选择 3D 视口。',
           'select_success': '已选择区域（{w}×{h}），可以保存 PNG。',
           'select_cancel': '已取消区域选择。',
           'taking': '正在截图…',
           'saved_png': '已保存 PNG：{path}',
           'need_region': '请先通过①选择视口区域。',
           'bad_dir': '保存文件夹不存在，请重新选择。',
           'no_screen': '无法找到所在显示器，请重新选择区域。',
           'outside': '截图区域超出显示器或跨越多个屏幕，请重新选择。',
           'grab_fail': '截图失败，请确认 Painter 窗口可见。',
           'png_fail': 'PNG 保存失败：{path}',
           'batch_progress': '正在拍摄 {count} 个视角，请不要遮挡 Painter。',
           'no_views': '可见书签中没有已保存的视角。',
           'batch_success': '已合并 {count} 个视角：{path}',
           'error': '错误：{error}',
           'language_auto_tip': '自动优先使用 Qt 应用语言，其次系统语言。不支持的语言默认英语。',
           'restore_failed': '无法恢复原始相机：{error}',
           'no_images': '没有可合并的截图。',
           'image_too_large': '请缩小视口截图区域后重试。',
           'out_of_memory': '合并图像的内存不足。'},
 'zh_TW': {'auto': '自動（程式 / 系統）',
           'language': '語言：',
           'pin': 'Tab 全螢幕時保持顯示（置頂）',
           'pin_tip': '切換為獨立置頂視窗，嘗試在按 Tab 隱藏 Painter 介面時持續顯示。',
           'note': '儲存目前相機視角，隨時快速返回。',
           'slots': '相機書籤數量：',
           'slot_suffix': '個',
           'view': '視角 {n}',
           'save': '儲存',
           'go': '前往',
           'refresh': '重新整理專案書籤',
           'screenshots': '3D 視埠截圖 (PNG)',
           'hint': '保留原始長寬比 · 首次指定範圍，之後一鍵儲存',
           'select_region': '① 指定視埠區域',
           'screenshot': '② 儲存 PNG 截圖',
           'all_title': '將已儲存視角合併成一張圖片',
           'all_desc': '依序拍攝已儲存視角。預設維持原始比例，略過空白及隱藏書籤。',
           'layout': '排列：',
           'layout_row': '橫向單列（原始比例）',
           'layout_three': '三欄網格',
           'layout_two': '兩欄網格',
           'gap': '間距：',
           'crop': '選用：置中裁切為 1:2 直式（預設關閉）',
           'crop_tip': '關閉時保留原始比例；開啟則置中裁切為 1:2，不拉伸影像。',
           'ratio_hint': '保留原始像素（支援 Windows 縮放比例）\n拼接時不縮小截圖。',
           'delay': '渲染等待：',
           'batch': '③ 拍攝並合併所有視角（維持比例）',
           'batch_tip': '以原始像素尺寸合併顯示中的書籤，直式裁切可自行選擇。',
           'region_unset': '截圖區域：尚未設定（按①）',
           'region_set': '截圖區域：{w} × {h}（螢幕座標）',
           'output': '儲存至：',
           'browse': '變更資料夾',
           'choose_folder': '選擇 PNG 儲存資料夾',
           'selector_title': '選取 Painter 3D 視埠',
           'selector_help': '拖曳選取 3D 視埠 · Esc 取消',
           'switching': '正在切換視窗模式…',
           'project_needed': '請先開啟 Painter 專案。沒有專案仍可截圖。',
           'bookmarks_ready': '相機書籤已就緒。',
           'saved': '已儲存 {name}。請記得儲存 .spp 專案。',
           'empty': '此書籤為空。',
           'moved': '已前往 {name}。',
           'select_instruction': '請在 Painter 中拖曳選取 3D 視埠。',
           'select_success': '已指定截圖範圍（{w}×{h}），可儲存 PNG。',
           'select_cancel': '已取消範圍選取。',
           'taking': '正在截圖…',
           'saved_png': 'PNG 已儲存：{path}',
           'need_region': '請先按①指定視埠區域。',
           'bad_dir': '儲存資料夾不存在，請重新選擇。',
           'no_screen': '找不到對應螢幕，請重新選取範圍。',
           'outside': '截圖範圍超出螢幕或跨越多個顯示器，請重新選擇。',
           'grab_fail': '截圖失敗，請確認 Painter 視窗顯示中。',
           'png_fail': 'PNG 儲存失敗：{path}',
           'batch_progress': '正在拍攝 {count} 個視角，請勿遮擋 Painter。',
           'no_views': '目前顯示的書籤中沒有已儲存的視角。',
           'batch_success': '已合併 {count} 個視角：{path}',
           'error': '錯誤：{error}',
           'language_auto_tip': '自動優先使用 Qt 程式語言，其次系統語言。不支援的語言預設使用英文。',
           'restore_failed': '無法復原原始相機：{error}',
           'no_images': '沒有可合併的截圖。',
           'image_too_large': '請縮小視埠截圖區域再試。',
           'out_of_memory': '合併影像的記憶體不足。'},
 'es': {'auto': 'Auto (aplicación / sistema)',
        'language': 'Idioma:',
        'pin': 'Visible con Tab (siempre encima)',
        'pin_tip': 'Abre una ventana independiente siempre visible al ocultar la interfaz de Painter con '
                   'Tab.',
        'note': 'Guarda la cámara actual y vuelve a esa vista cuando quieras.',
        'slots': 'Marcadores de cámara:',
        'slot_suffix': '',
        'view': 'Vista {n}',
        'save': 'Guardar',
        'go': 'Ir',
        'refresh': 'Actualizar marcadores',
        'screenshots': 'CAPTURAS DEL VISOR 3D (PNG)',
        'hint': 'Proporción original · Selecciona el área una vez y guarda PNG',
        'select_region': '① Seleccionar área del visor',
        'screenshot': '② Guardar captura PNG',
        'all_title': 'UNIR TODAS LAS VISTAS EN UNA IMAGEN',
        'all_desc': 'Captura los marcadores en orden. Conserva la proporción original y omite los vacíos u '
                    'ocultos.',
        'layout': 'Diseño:',
        'layout_row': 'Fila horizontal (proporción original)',
        'layout_three': 'Cuadrícula de 3 columnas',
        'layout_two': 'Cuadrícula de 2 columnas',
        'gap': 'Separación:',
        'crop': 'Opcional: recorte vertical 1:2 centrado (desactivado)',
        'crop_tip': 'Desactivado conserva la proporción; activado recorta en 1:2 sin estirar.',
        'ratio_hint': 'Conserva los píxeles originales (corrección de escala de Windows).\n'
                      'No reduce las capturas al unirlas.',
        'delay': 'Espera de render:',
        'batch': '③ Capturar y unir todas las vistas',
        'batch_tip': 'Une los marcadores visibles a su tamaño original; el recorte es opcional.',
        'region_unset': 'Área: sin definir (botón ①)',
        'region_set': 'Área: {w} × {h} (pantalla)',
        'output': 'Guardar en:',
        'browse': 'Cambiar carpeta',
        'choose_folder': 'Elegir carpeta para PNG',
        'selector_title': 'Seleccionar visor 3D de Painter',
        'selector_help': 'Arrastra para seleccionar SOLO el visor 3D · Esc cancela',
        'switching': 'Cambiando modo de ventana…',
        'project_needed': 'Abre un proyecto primero. Puedes capturar sin proyecto.',
        'bookmarks_ready': 'Marcadores listos.',
        'saved': '{name} guardada. Guarda también el proyecto .spp.',
        'empty': 'Este marcador está vacío.',
        'moved': 'Vista cambiada a {name}.',
        'select_instruction': 'Arrastra para delimitar el visor 3D de Painter.',
        'select_success': 'Área seleccionada ({w}×{h}). Ya puedes guardar PNG.',
        'select_cancel': 'Selección cancelada.',
        'taking': 'Capturando…',
        'saved_png': 'PNG guardado: {path}',
        'need_region': 'Selecciona primero el área (botón ①).',
        'bad_dir': 'La carpeta no existe. Elige otra.',
        'no_screen': 'No se encontró la pantalla. Selecciona otra vez.',
        'outside': 'El área está fuera de pantalla o cruza monitores.',
        'grab_fail': 'Error de captura. Comprueba que Painter esté visible.',
        'png_fail': 'No se pudo guardar PNG: {path}',
        'batch_progress': 'Capturando {count} vistas… No tapes Painter.',
        'no_views': 'No hay vistas guardadas entre los marcadores visibles.',
        'batch_success': '{count} vistas combinadas. PNG: {path}',
        'error': 'Error: {error}',
        'language_auto_tip': 'Auto usa el idioma Qt de la aplicación y, después, el del sistema. Idiomas '
                             'no compatibles: inglés.',
        'restore_failed': 'No se pudo restaurar la cámara original: {error}',
        'no_images': 'No hay capturas para combinar.',
        'image_too_large': 'Selecciona un área de captura más pequeña.',
        'out_of_memory': 'Memoria insuficiente para la imagen combinada.'},
 'fr': {'auto': 'Auto (application / système)',
        'language': 'Langue :',
        'pin': 'Rester visible avec Tab (toujours au-dessus)',
        'pin_tip': 'Passe à une fenêtre indépendante toujours au-dessus pour rester visible lorsque Tab '
                   'masque l’interface.',
        'note': 'Enregistrez la caméra actuelle et retrouvez cette vue à tout moment.',
        'slots': 'Signets caméra :',
        'slot_suffix': '',
        'view': 'Vue {n}',
        'save': 'Enregistrer',
        'go': 'Aller',
        'refresh': 'Actualiser les signets',
        'screenshots': 'CAPTURES DE LA VUE 3D (PNG)',
        'hint': 'Format d’origine · Définissez la zone une fois, puis enregistrez en PNG',
        'select_region': '① Sélectionner la zone 3D',
        'screenshot': '② Enregistrer un PNG',
        'all_title': 'ASSEMBLER TOUTES LES VUES EN UNE IMAGE',
        'all_desc': 'Capture les signets dans l’ordre, au format original, sans les emplacements vides ou '
                    'masqués.',
        'layout': 'Disposition :',
        'layout_row': 'Une ligne (format d’origine)',
        'layout_three': 'Grille 3 colonnes',
        'layout_two': 'Grille 2 colonnes',
        'gap': 'Espacement :',
        'crop': 'Option : recadrage vertical 1:2 centré (désactivé)',
        'crop_tip': 'Désactivé = format d’origine ; activé = recadrage 1:2 sans étirement.',
        'ratio_hint': 'Préserve les pixels (correction du zoom d’affichage Windows).\n'
                      'Aucune réduction lors de l’assemblage.',
        'delay': 'Attente du rendu :',
        'batch': '③ Capturer et assembler toutes les vues',
        'batch_tip': 'Assemble les vues visibles à leur taille d’origine. Recadrage facultatif.',
        'region_unset': 'Zone : non définie (bouton ①)',
        'region_set': 'Zone : {w} × {h} (écran)',
        'output': 'Dossier :',
        'browse': 'Changer',
        'choose_folder': 'Choisir le dossier PNG',
        'selector_title': 'Sélectionner la vue 3D de Painter',
        'selector_help': 'Faites glisser sur la vue 3D uniquement · Esc annule',
        'switching': 'Changement du mode de fenêtre…',
        'project_needed': 'Ouvrez un projet. Une capture reste possible sans projet.',
        'bookmarks_ready': 'Signets caméra prêts.',
        'saved': '{name} enregistrée. Pensez à sauver le projet .spp.',
        'empty': 'Ce signet est vide.',
        'moved': 'Vue {name} affichée.',
        'select_instruction': 'Tracez un rectangle autour de la vue 3D Painter.',
        'select_success': 'Zone sélectionnée ({w}×{h}). PNG prêt.',
        'select_cancel': 'Sélection annulée.',
        'taking': 'Capture en cours…',
        'saved_png': 'PNG enregistré : {path}',
        'need_region': 'Sélectionnez d’abord la zone (bouton ①).',
        'bad_dir': 'Le dossier n’existe pas. Choisissez-en un autre.',
        'no_screen': 'Écran introuvable. Sélectionnez de nouveau.',
        'outside': 'La zone est hors écran ou sur plusieurs écrans.',
        'grab_fail': 'Échec de capture. Vérifiez que Painter est visible.',
        'png_fail': 'Impossible d’enregistrer PNG : {path}',
        'batch_progress': 'Capture de {count} vues… Ne masquez pas Painter.',
        'no_views': 'Aucune vue enregistrée parmi les signets visibles.',
        'batch_success': '{count} vues assemblées : {path}',
        'error': 'Erreur : {error}',
        'language_auto_tip': 'Auto utilise la langue Qt de l’application, puis celle du système. Anglais '
                             'par défaut.',
        'restore_failed': 'Impossible de restaurer la caméra initiale : {error}',
        'no_images': 'Aucune capture à assembler.',
        'image_too_large': 'Choisissez une zone de capture plus petite.',
        'out_of_memory': 'Mémoire insuffisante pour l’image assemblée.'},
 'de': {'auto': 'Auto (App / System)',
        'language': 'Sprache:',
        'pin': 'Bei Tab-Vollbild sichtbar (immer im Vordergrund)',
        'pin_tip': 'Wechselt zu einem separaten Fenster im Vordergrund, damit es beim Ausblenden der '
                   'Painter-Oberfläche sichtbar bleibt.',
        'note': 'Aktuelle Kameraposition speichern und jederzeit wieder aufrufen.',
        'slots': 'Kamera-Lesezeichen:',
        'slot_suffix': '',
        'view': 'Ansicht {n}',
        'save': 'Speichern',
        'go': 'Aufrufen',
        'refresh': 'Lesezeichen aktualisieren',
        'screenshots': '3D-ANSICHT SCREENSHOTS (PNG)',
        'hint': 'Originalverhältnis · Bereich einmal auswählen, dann PNG speichern',
        'select_region': '① Ansichtsbereich wählen',
        'screenshot': '② PNG-Screenshot speichern',
        'all_title': 'ALLE GESPEICHERTEN ANSICHTEN KOMBINIEREN',
        'all_desc': 'Gespeicherte Ansichten nacheinander aufnehmen. Originalverhältnis beibehalten; leere '
                    'und ausgeblendete überspringen.',
        'layout': 'Anordnung:',
        'layout_row': 'Eine horizontale Reihe (Originalverhältnis)',
        'layout_three': '3-Spalten-Raster',
        'layout_two': '2-Spalten-Raster',
        'gap': 'Abstand:',
        'crop': 'Optional: mittig auf 1:2 Hochformat zuschneiden (AUS)',
        'crop_tip': 'AUS behält das Originalverhältnis; EIN schneidet mittig auf 1:2 zu, ohne Strecken.',
        'ratio_hint': 'Originalpixel erhalten (Windows-Skalierung korrigiert).\n'
                      'Keine Verkleinerung beim Zusammenfügen.',
        'delay': 'Renderwartezeit:',
        'batch': '③ Alle Ansichten aufnehmen und kombinieren',
        'batch_tip': 'Sichtbare Ansichten in Originalpixelgröße kombinieren. Hochformat-Zuschnitt ist '
                     'optional.',
        'region_unset': 'Aufnahmebereich: nicht festgelegt (①)',
        'region_set': 'Aufnahmebereich: {w} × {h} (Bildschirm)',
        'output': 'Speichern unter:',
        'browse': 'Ordner wählen',
        'choose_folder': 'PNG-Ausgabeordner wählen',
        'selector_title': 'Painter 3D-Ansicht wählen',
        'selector_help': 'Nur 3D-Ansicht mit Maus aufziehen · Esc = Abbrechen',
        'switching': 'Fenstermodus wird geändert…',
        'project_needed': 'Zuerst ein Projekt öffnen. Screenshots gehen auch ohne Projekt.',
        'bookmarks_ready': 'Kamera-Lesezeichen bereit.',
        'saved': '{name} gespeichert. Bitte auch das .spp-Projekt speichern.',
        'empty': 'Dieses Lesezeichen ist leer.',
        'moved': 'Zu {name} gewechselt.',
        'select_instruction': 'Ziehen Sie ein Rechteck um die 3D-Ansicht in Painter.',
        'select_success': 'Bereich gewählt ({w}×{h}). PNG kann gespeichert werden.',
        'select_cancel': 'Auswahl abgebrochen.',
        'taking': 'Screenshot wird aufgenommen…',
        'saved_png': 'PNG gespeichert: {path}',
        'need_region': 'Bitte erst den Bereich mit ① wählen.',
        'bad_dir': 'Ausgabeordner fehlt. Anderen Ordner wählen.',
        'no_screen': 'Bildschirm nicht gefunden. Bereich erneut wählen.',
        'outside': 'Bereich außerhalb des Bildschirms oder über mehrere Monitore.',
        'grab_fail': 'Aufnahme fehlgeschlagen. Painter muss sichtbar sein.',
        'png_fail': 'PNG konnte nicht gespeichert werden: {path}',
        'batch_progress': 'Nehme {count} Ansichten auf… Painter nicht verdecken.',
        'no_views': 'Keine gespeicherten Ansichten in den sichtbaren Slots.',
        'batch_success': '{count} Ansichten kombiniert: {path}',
        'error': 'Fehler: {error}',
        'language_auto_tip': 'Auto nutzt die Qt-App-Sprache, dann die Systemsprache. Nicht unterstützte '
                             'Sprachen: Englisch.',
        'restore_failed': 'Ursprüngliche Kamera konnte nicht wiederhergestellt werden: {error}',
        'no_images': 'Keine Bilder zum Kombinieren vorhanden.',
        'image_too_large': 'Kleineren Aufnahmebereich wählen und erneut versuchen.',
        'out_of_memory': 'Nicht genug Speicher für das kombinierte Bild.'},
 'pt': {'auto': 'Auto (aplicativo / sistema)',
        'language': 'Idioma:',
        'pin': 'Visível com Tab (sempre no topo)',
        'pin_tip': 'Abre uma janela independente sempre no topo para tentar permanecer visível quando Tab '
                   'oculta a interface.',
        'note': 'Salve a câmera atual e volte a essa vista quando quiser.',
        'slots': 'Marcadores de câmera:',
        'slot_suffix': '',
        'view': 'Vista {n}',
        'save': 'Salvar',
        'go': 'Ir',
        'refresh': 'Atualizar marcadores',
        'screenshots': 'CAPTURAS DA VIEWPORT 3D (PNG)',
        'hint': 'Proporção original · Selecione a área uma vez e salve PNG',
        'select_region': '① Selecionar área da viewport',
        'screenshot': '② Salvar captura PNG',
        'all_title': 'JUNTAR TODAS AS VISTAS EM UMA IMAGEM',
        'all_desc': 'Captura os marcadores em ordem. Mantém a proporção original e ignora marcadores '
                    'vazios ou ocultos.',
        'layout': 'Layout:',
        'layout_row': 'Linha horizontal (proporção original)',
        'layout_three': 'Grade de 3 colunas',
        'layout_two': 'Grade de 2 colunas',
        'gap': 'Espaço:',
        'crop': 'Opcional: recorte vertical central 1:2 (desligado)',
        'crop_tip': 'Desligado preserva a proporção; ligado recorta 1:2 sem esticar.',
        'ratio_hint': 'Mantém os pixels originais (correção de escala do Windows).\n'
                      'Não reduz as capturas ao combinar.',
        'delay': 'Espera da renderização:',
        'batch': '③ Capturar e juntar todas as vistas',
        'batch_tip': 'Combina as vistas visíveis no tamanho original. O recorte é opcional.',
        'region_unset': 'Área: não definida (botão ①)',
        'region_set': 'Área: {w} × {h} (tela)',
        'output': 'Salvar em:',
        'browse': 'Mudar pasta',
        'choose_folder': 'Escolher pasta de PNG',
        'selector_title': 'Selecionar viewport 3D do Painter',
        'selector_help': 'Arraste somente sobre a viewport 3D · Esc cancela',
        'switching': 'Mudando modo da janela…',
        'project_needed': 'Abra um projeto primeiro. Capturas funcionam sem projeto.',
        'bookmarks_ready': 'Marcadores prontos.',
        'saved': '{name} salva. Salve também o projeto .spp.',
        'empty': 'Este marcador está vazio.',
        'moved': 'Exibindo {name}.',
        'select_instruction': 'Arraste para selecionar a viewport 3D do Painter.',
        'select_success': 'Área selecionada ({w}×{h}). Pronto para salvar PNG.',
        'select_cancel': 'Seleção cancelada.',
        'taking': 'Capturando imagem…',
        'saved_png': 'PNG salvo: {path}',
        'need_region': 'Selecione a área primeiro (botão ①).',
        'bad_dir': 'Pasta de destino inexistente. Escolha outra.',
        'no_screen': 'Tela não encontrada. Selecione de novo.',
        'outside': 'Área fora da tela ou dividida entre monitores.',
        'grab_fail': 'Falha na captura. Verifique se Painter está visível.',
        'png_fail': 'Falha ao salvar PNG: {path}',
        'batch_progress': 'Capturando {count} vistas… Não cubra o Painter.',
        'no_views': 'Nenhuma vista salva nos marcadores visíveis.',
        'batch_success': '{count} vistas combinadas: {path}',
        'error': 'Erro: {error}',
        'language_auto_tip': 'Auto usa o idioma Qt do aplicativo, depois o sistema. Idiomas não suportados '
                             'usam inglês.',
        'restore_failed': 'Não foi possível restaurar a câmera original: {error}',
        'no_images': 'Não há capturas para combinar.',
        'image_too_large': 'Escolha uma área de captura menor e tente novamente.',
        'out_of_memory': 'Memória insuficiente para a imagem combinada.'},
 'ru': {'auto': 'Авто (приложение / система)',
        'language': 'Язык:',
        'pin': 'Не скрывать при Tab (поверх окон)',
        'pin_tip': 'Открывает отдельное окно поверх остальных, чтобы оно оставалось видимым при скрытии '
                   'интерфейса Painter.',
        'note': 'Сохраните текущий ракурс камеры и вернитесь к нему в любой момент.',
        'slots': 'Закладки камеры:',
        'slot_suffix': '',
        'view': 'Вид {n}',
        'save': 'Сохранить',
        'go': 'Перейти',
        'refresh': 'Обновить закладки',
        'screenshots': 'СКРИНШОТЫ 3D-ОКНА (PNG)',
        'hint': 'Сохранение пропорций · Выберите область один раз, затем сохраняйте PNG',
        'select_region': '① Выбрать область 3D-окна',
        'screenshot': '② Сохранить PNG',
        'all_title': 'ОБЪЕДИНИТЬ ВСЕ СОХРАНЁННЫЕ ВИДЫ',
        'all_desc': 'Снимает закладки по порядку, сохраняя пропорции. Пустые и скрытые слоты пропускаются.',
        'layout': 'Макет:',
        'layout_row': 'В один ряд (исходные пропорции)',
        'layout_three': 'Сетка 3 столбца',
        'layout_two': 'Сетка 2 столбца',
        'gap': 'Интервал:',
        'crop': 'Дополнительно: обрезка по центру 1:2 (выкл.)',
        'crop_tip': 'ВЫКЛ — исходные пропорции; ВКЛ — обрезка до 1:2 без растяжения.',
        'ratio_hint': 'Сохранение исходных пикселей (масштабирование Windows).\n'
                      'Без уменьшения кадров при объединении.',
        'delay': 'Ожидание рендера:',
        'batch': '③ Снять и объединить все виды',
        'batch_tip': 'Объединяет видимые слоты в исходном размере. Обрезка необязательна.',
        'region_unset': 'Область: не задана (кнопка ①)',
        'region_set': 'Область: {w} × {h} (экран)',
        'output': 'Папка:',
        'browse': 'Выбрать папку',
        'choose_folder': 'Выберите папку для PNG',
        'selector_title': 'Выбрать 3D-окно Painter',
        'selector_help': 'Выделите только 3D-окно мышью · Esc — отмена',
        'switching': 'Переключение режима окна…',
        'project_needed': 'Откройте проект. Скриншоты доступны и без проекта.',
        'bookmarks_ready': 'Закладки камеры готовы.',
        'saved': '{name} сохранён. Сохраните также проект .spp.',
        'empty': 'Закладка пуста.',
        'moved': 'Перешли к {name}.',
        'select_instruction': 'Выделите прямоугольником 3D-окно Painter.',
        'select_success': 'Область выбрана ({w}×{h}). Можно сохранить PNG.',
        'select_cancel': 'Выбор отменён.',
        'taking': 'Снимок экрана…',
        'saved_png': 'PNG сохранён: {path}',
        'need_region': 'Сначала выберите область (кнопка ①).',
        'bad_dir': 'Папка не найдена. Выберите другую.',
        'no_screen': 'Монитор не найден. Выберите область снова.',
        'outside': 'Область выходит за экран или захватывает несколько мониторов.',
        'grab_fail': 'Сбой снимка. Убедитесь, что Painter видим.',
        'png_fail': 'Ошибка сохранения PNG: {path}',
        'batch_progress': 'Съёмка {count} видов… Не перекрывайте окно Painter.',
        'no_views': 'Среди видимых слотов нет сохранённых видов.',
        'batch_success': 'Объединено {count} видов: {path}',
        'error': 'Ошибка: {error}',
        'language_auto_tip': 'Авто: язык Qt-приложения, затем системы. При отсутствии перевода — '
                             'английский.',
        'restore_failed': 'Не удалось восстановить исходную камеру: {error}',
        'no_images': 'Нет снимков для объединения.',
        'image_too_large': 'Выберите меньшую область для снимка.',
        'out_of_memory': 'Недостаточно памяти для итогового изображения.'},
 'it': {'auto': 'Auto (app / sistema)',
        'language': 'Lingua:',
        'pin': 'Visibile con Tab (sempre in primo piano)',
        'pin_tip': 'Passa a una finestra indipendente sempre in primo piano per restare visibile con Tab.',
        'note': 'Salva la telecamera attuale e torna alla vista in qualsiasi momento.',
        'slots': 'Segnalibri telecamera:',
        'slot_suffix': '',
        'view': 'Vista {n}',
        'save': 'Salva',
        'go': 'Vai',
        'refresh': 'Aggiorna segnalibri',
        'screenshots': 'SCHERMATE VIEWPORT 3D (PNG)',
        'hint': 'Proporzioni originali · Seleziona una volta l’area, poi salva PNG',
        'select_region': '① Seleziona area viewport',
        'screenshot': '② Salva screenshot PNG',
        'all_title': 'UNISCI TUTTE LE VISTE IN UNA SOLA IMMAGINE',
        'all_desc': 'Acquisisce i segnalibri in ordine, mantiene le proporzioni e salta gli slot vuoti o '
                    'nascosti.',
        'layout': 'Layout:',
        'layout_row': 'Riga orizzontale (proporzioni originali)',
        'layout_three': 'Griglia 3 colonne',
        'layout_two': 'Griglia 2 colonne',
        'gap': 'Spazio:',
        'crop': 'Opzionale: ritaglio verticale centrale 1:2 (OFF)',
        'crop_tip': 'OFF mantiene le proporzioni; ON ritaglia al centro 1:2 senza deformare.',
        'ratio_hint': 'Mantiene i pixel originali (correzione scala Windows).\n'
                      'Nessuna riduzione durante l’unione.',
        'delay': 'Attesa render:',
        'batch': '③ Acquisisci e unisci tutte le viste',
        'batch_tip': 'Unisce gli slot visibili alla dimensione originale. Ritaglio facoltativo.',
        'region_unset': 'Area: non definita (pulsante ①)',
        'region_set': 'Area: {w} × {h} (schermo)',
        'output': 'Salva in:',
        'browse': 'Cambia cartella',
        'choose_folder': 'Scegli cartella PNG',
        'selector_title': 'Seleziona la viewport 3D di Painter',
        'selector_help': 'Trascina solo sulla viewport 3D · Esc annulla',
        'switching': 'Cambio modalità finestra…',
        'project_needed': 'Apri prima un progetto. Gli screenshot sono disponibili anche senza.',
        'bookmarks_ready': 'Segnalibri pronti.',
        'saved': '{name} salvata. Salva anche il progetto .spp.',
        'empty': 'Questo segnalibro è vuoto.',
        'moved': 'Vista {name} attivata.',
        'select_instruction': 'Trascina un rettangolo sulla viewport 3D di Painter.',
        'select_success': 'Area selezionata ({w}×{h}). Puoi salvare PNG.',
        'select_cancel': 'Selezione annullata.',
        'taking': 'Acquisizione in corso…',
        'saved_png': 'PNG salvato: {path}',
        'need_region': 'Seleziona prima l’area (pulsante ①).',
        'bad_dir': 'La cartella non esiste. Scegline un’altra.',
        'no_screen': 'Schermo non trovato. Seleziona di nuovo.',
        'outside': 'L’area esce dallo schermo o attraversa più monitor.',
        'grab_fail': 'Acquisizione fallita. Verifica che Painter sia visibile.',
        'png_fail': 'Impossibile salvare PNG: {path}',
        'batch_progress': 'Acquisizione di {count} viste… Non coprire Painter.',
        'no_views': 'Nessuna vista salvata tra gli slot visibili.',
        'batch_success': '{count} viste unite: {path}',
        'error': 'Errore: {error}',
        'language_auto_tip': 'Auto usa la lingua Qt dell’app, poi quella del sistema. Le lingue non '
                             'supportate usano l’inglese.',
        'restore_failed': 'Impossibile ripristinare la telecamera originale: {error}',
        'no_images': 'Nessuna cattura da unire.',
        'image_too_large': 'Scegli un’area di cattura più piccola.',
        'out_of_memory': 'Memoria insufficiente per l’immagine unita.'}}



# ViewAtlas screenshot workflow controls; English is the fallback for every locale.
_NEW_SHOT_LABELS = {
    'en': ('File name:', 'Optional name (blank = automatic)',
           'Open image after saving', 'Could not open image viewer: {path}',
           'The screenshot was saved, but the image viewer could not be started.'),
    'ko': ('저장 파일명:', '비우면 날짜·시간으로 자동 저장',
           '저장 후 이미지 바로 열기', '이미지 뷰어를 열지 못했습니다: {path}',
           'PNG는 저장됐지만 이미지 뷰어를 열지 못했습니다.'),
    'ja': ('保存ファイル名:', '空欄なら日時で自動命名',
           '保存後に画像を開く', '画像ビューアを開けません: {path}',
           'PNGは保存されましたが、画像ビューアを開けませんでした。'),
    'zh_CN': ('保存文件名：', '留空则按日期时间自动命名',
              '保存后立即打开图片', '无法打开图片查看器：{path}',
              'PNG 已保存，但无法启动图片查看器。'),
    'zh_TW': ('儲存檔名：', '留空則依日期時間自動命名',
              '儲存後立即開啟圖片', '無法開啟圖片檢視器：{path}',
              'PNG 已儲存，但無法啟動圖片檢視器。'),
    'es': ('Nombre de archivo:', 'Vacío = nombre automático',
           'Abrir imagen después de guardar', 'No se pudo abrir el visor: {path}',
           'El PNG se guardó, pero no se pudo abrir el visor.'),
    'fr': ('Nom du fichier :', 'Vide = nom automatique',
           'Ouvrir l’image après enregistrement', 'Impossible d’ouvrir la visionneuse : {path}',
           'Le PNG a été enregistré, mais la visionneuse ne s’ouvre pas.'),
    'de': ('Dateiname:', 'Leer = automatisch benennen',
           'Bild nach dem Speichern öffnen', 'Bildanzeige konnte nicht geöffnet werden: {path}',
           'PNG wurde gespeichert, aber die Bildanzeige konnte nicht geöffnet werden.'),
    'pt': ('Nome do arquivo:', 'Vazio = nome automático',
           'Abrir imagem após salvar', 'Não foi possível abrir a imagem: {path}',
           'O PNG foi salvo, mas o visualizador não abriu.'),
    'ru': ('Имя файла:', 'Пусто = автоматическое имя',
           'Открывать изображение после сохранения', 'Не удалось открыть изображение: {path}',
           'PNG сохранён, но не удалось запустить просмотрщик.'),
    'it': ('Nome del file:', 'Vuoto = nome automatico',
           'Apri immagine dopo il salvataggio', 'Impossibile aprire il visualizzatore: {path}',
           'Il PNG è stato salvato, ma il visualizzatore non si apre.'),
}
for _code, _parts in _NEW_SHOT_LABELS.items():
    _TRANSLATIONS[_code].update(dict(zip(
        ('file_name', 'file_name_hint', 'open_after', 'open_failed', 'open_failed_short'),
        _parts
    )))
del _code, _parts

# V12 UI labels. Any untranslated entry falls back to English.
_NEW_V12_LABELS = {'en': {'show_region': 'Show capture area', 'show_region_tip': 'Show the exact screen rectangle used for screenshots. Click or press Esc to close.', 'overlay_help': 'SCREENSHOT CAPTURE AREA · Click anywhere or press Esc to close', 'select_views': 'Select views to include:', 'select_all': 'Select all', 'select_none': 'Select none', 'thumbnail_missing': 'No preview', 'thumbnail_tip': 'View saved thumbnail; generated from the selected viewport area when the bookmark is saved.', 'thumbnail_pending': 'Saving camera… capturing thumbnail', 'thumbnail_done': 'Saved {name} with thumbnail. Save your .spp project.', 'thumbnail_need_region': 'Camera saved. Set capture area to create a thumbnail next time.', 'no_selected_views': 'No checked saved views. Tick at least one saved bookmark.', 'batch_desc_selected': 'Only checked saved views are included in the contact sheet.', 'region_window_error': 'This capture area is not on the current Painter window. Select the region again.'}, 'ko': {'show_region': '촬영 범위 표시', 'show_region_tip': '실제로 스크린샷에 담길 영역을 테두리로 표시합니다. 클릭하거나 Esc로 닫습니다.', 'overlay_help': '스크린샷 촬영 범위 · 클릭 또는 Esc로 닫기', 'select_views': '일괄 촬영에 포함할 뷰:', 'select_all': '전체 선택', 'select_none': '전체 해제', 'thumbnail_missing': '미리보기 없음', 'thumbnail_tip': '저장된 뷰의 미리보기입니다. 영역 지정 후 카메라를 저장하면 자동으로 생성됩니다.', 'thumbnail_pending': '카메라 저장 완료 · 썸네일 촬영 중…', 'thumbnail_done': '{name} 저장 및 썸네일 생성 완료. .spp도 저장해 주세요.', 'thumbnail_need_region': '카메라는 저장했어. 범위를 설정한 뒤 다시 저장하면 썸네일이 만들어져.', 'no_selected_views': '체크된 저장 뷰가 없어. 촬영할 슬롯을 하나 이상 체크해 줘.', 'batch_desc_selected': '체크한 저장 뷰만 촬영해 한 장으로 합칩니다.', 'region_window_error': '현재 Painter 창에서 촬영 영역을 찾을 수 없어. 영역을 다시 지정해 줘.'}, 'ja': {'show_region': '撮影範囲を表示', 'overlay_help': '撮影範囲・クリックまたはEscで閉じる', 'select_views': '一括撮影するビュー:', 'select_all': 'すべて選択', 'select_none': 'すべて解除', 'thumbnail_missing': 'プレビューなし', 'thumbnail_pending': 'サムネイルを撮影中…', 'thumbnail_done': '{name} の保存とサムネイルの作成が完了。', 'thumbnail_need_region': 'ビューを保存しました。範囲を指定すると次回からサムネイルが作成されます。', 'no_selected_views': 'チェックした保存ビューがありません。'}, 'zh_CN': {'show_region': '显示截图范围', 'overlay_help': '截图范围 · 点击或 Esc 关闭', 'select_views': '批量截图视图：', 'select_all': '全选', 'select_none': '取消全选', 'thumbnail_missing': '无预览', 'thumbnail_pending': '正在生成缩略图…', 'thumbnail_done': '已保存 {name} 和缩略图。', 'thumbnail_need_region': '视图已保存。选择截图范围后可生成缩略图。', 'no_selected_views': '没有勾选已保存的视图。'}, 'zh_TW': {'show_region': '顯示擷取範圍', 'overlay_help': '擷取範圍 · 點擊或 Esc 關閉', 'select_views': '批次擷取檢視：', 'select_all': '全部選取', 'select_none': '全部取消', 'thumbnail_missing': '無預覽', 'thumbnail_pending': '正在產生縮圖…', 'thumbnail_done': '已儲存 {name} 和縮圖。', 'thumbnail_need_region': '檢視已儲存。設定擷取範圍後可產生縮圖。', 'no_selected_views': '沒有勾選已儲存的檢視。'}, 'es': {'show_region': 'Mostrar área de captura', 'overlay_help': 'ÁREA DE CAPTURA · Clic o Esc para cerrar', 'select_views': 'Vistas para captura:', 'select_all': 'Seleccionar todas', 'select_none': 'Deseleccionar', 'thumbnail_missing': 'Sin vista previa', 'thumbnail_pending': 'Creando miniatura…', 'thumbnail_done': '{name} guardado con miniatura.', 'thumbnail_need_region': 'Vista guardada. Define el área de captura para generar miniaturas.', 'no_selected_views': 'No hay vistas guardadas seleccionadas.'}, 'fr': {'show_region': 'Afficher la zone de capture', 'overlay_help': 'ZONE DE CAPTURE · Cliquez ou appuyez sur Échap', 'select_views': 'Vues à capturer :', 'select_all': 'Tout sélectionner', 'select_none': 'Tout désélectionner', 'thumbnail_missing': 'Pas d’aperçu', 'thumbnail_pending': 'Création de la miniature…', 'thumbnail_done': '{name} enregistré avec sa miniature.', 'thumbnail_need_region': 'Vue enregistrée. Définissez la zone de capture pour créer un aperçu.', 'no_selected_views': 'Aucune vue enregistrée sélectionnée.'}, 'de': {'show_region': 'Aufnahmebereich anzeigen', 'overlay_help': 'AUFNAHMEBEREICH · Klicken oder Esc zum Schließen', 'select_views': 'Ansichten für Aufnahme:', 'select_all': 'Alle auswählen', 'select_none': 'Keine auswählen', 'thumbnail_missing': 'Keine Vorschau', 'thumbnail_pending': 'Vorschaubild wird erstellt…', 'thumbnail_done': '{name} mit Vorschaubild gespeichert.', 'thumbnail_need_region': 'Ansicht gespeichert. Für Vorschaubilder bitte Aufnahmebereich festlegen.', 'no_selected_views': 'Keine gespeicherten Ansichten ausgewählt.'}, 'pt': {'show_region': 'Mostrar área de captura', 'overlay_help': 'ÁREA DE CAPTURA · Clique ou Esc para fechar', 'select_views': 'Vistas para capturar:', 'select_all': 'Selecionar todas', 'select_none': 'Limpar seleção', 'thumbnail_missing': 'Sem prévia', 'thumbnail_pending': 'Criando miniatura…', 'thumbnail_done': '{name} salvo com miniatura.', 'thumbnail_need_region': 'Vista salva. Defina a área de captura para gerar a miniatura.', 'no_selected_views': 'Nenhuma vista salva selecionada.'}, 'ru': {'show_region': 'Показать область снимка', 'overlay_help': 'ОБЛАСТЬ СНИМКА · Нажмите или Esc, чтобы закрыть', 'select_views': 'Виды для снимка:', 'select_all': 'Выбрать все', 'select_none': 'Снять выбор', 'thumbnail_missing': 'Нет превью', 'thumbnail_pending': 'Создание миниатюры…', 'thumbnail_done': '{name} и миниатюра сохранены.', 'thumbnail_need_region': 'Вид сохранён. Выберите область снимка для миниатюры.', 'no_selected_views': 'Нет выбранных сохранённых видов.'}, 'it': {'show_region': 'Mostra area di cattura', 'overlay_help': 'AREA DI CATTURA · Clic o Esc per chiudere', 'select_views': 'Viste da acquisire:', 'select_all': 'Seleziona tutto', 'select_none': 'Deseleziona tutto', 'thumbnail_missing': 'Nessuna anteprima', 'thumbnail_pending': 'Creazione miniatura…', 'thumbnail_done': '{name} salvato con miniatura.', 'thumbnail_need_region': 'Vista salvata. Seleziona un’area per creare una miniatura.', 'no_selected_views': 'Nessuna vista salvata selezionata.'}}
for _code, _labels in _NEW_V12_LABELS.items():
    _TRANSLATIONS[_code].update(_labels)
del _code, _labels

def _normalize_language(name):
    code = str(name or '').replace('-', '_').lower()
    base = code.split('_', 1)[0]
    if base == 'zh':
        if any(part in code for part in ('tw', 'hk', 'mo', 'hant')):
            return 'zh_TW'
        return 'zh_CN'
    if base in ('en', 'ko', 'ja', 'es', 'fr', 'de', 'pt', 'ru', 'it'):
        return base
    return None


def _detected_language():
    # Prefer Painter's Qt main-window locale over OS language when available.
    locales = []
    try:
        locales.append(ui.get_main_window().locale())
    except Exception:
        pass
    try:
        locales.append(QtCore.QLocale())
    except Exception:
        pass
    try:
        locales.append(QtCore.QLocale.system())
    except Exception:
        pass
    for value in locales:
        try:
            names = value.uiLanguages() + [value.name()]
        except Exception:
            continue
        for name in names:
            code = _normalize_language(name)
            if code:
                return code
    return 'en'


def _language_setting():
    code = str(_settings().value('ui_language_v10', 'en'))
    return code if code in dict(_LANGUAGES) else 'en'


def _current_language():
    pref = _language_setting()
    return _detected_language() if pref == 'auto' else pref


def _tr(key, language=None, **values):
    code = language or _current_language()
    template = _TRANSLATIONS.get(code, _TRANSLATIONS['en']).get(
        key, _TRANSLATIONS['en'].get(key, key)
    )
    return template.format(**values) if values else template


def _camera():
    if not project.is_open():
        raise RuntimeError(_tr('project_needed'))
    if not hasattr(display, 'Camera') or not hasattr(display.Camera, 'get_default_camera'):
        raise RuntimeError('Camera bookmarks require Substance 3D Painter 9.1 or newer.')
    return display.Camera.get_default_camera()


def _metadata():
    return project.Metadata(_CONTEXT)


def _get_slots():
    slots = _metadata().get(_KEY)
    if not isinstance(slots, list):
        slots = []
    return (slots + [None] * _NUM_SLOTS)[:_NUM_SLOTS]


def _get_selection():
    """Saved per project; old projects default to selecting all slots."""
    if not project.is_open():
        return [True] * _NUM_SLOTS
    value = _metadata().get(_SELECTION_KEY)
    if isinstance(value, list):
        return [bool(v) for v in (value + [True] * _NUM_SLOTS)[:_NUM_SLOTS]]
    return [True] * _NUM_SLOTS


def _set_selection(values):
    if project.is_open():
        _metadata().set(_SELECTION_KEY, [bool(v) for v in values[:_NUM_SLOTS]])


def _thumbnail_from_pixmap(pixmap):
    """JPEG-encode a small screenshot as base64 for project.Metadata."""
    if pixmap.isNull():
        return ''
    image = pixmap.toImage()
    image.setDevicePixelRatio(1.0)
    # Thumbnail is for UI only: source screenshot proportions are maintained.
    scaled = image.scaled(480, 300,
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    if not buffer.open(QtCore.QIODevice.WriteOnly):
        return ''
    try:
        if not scaled.save(buffer, 'JPEG', 87):
            return ''
    finally:
        buffer.close()
    return base64.b64encode(bytes(data)).decode('ascii')


def _capture():
    c = _camera()
    return {
        "position": [float(v) for v in c.position],
        "rotation": [float(v) for v in c.rotation],
        "projection": c.projection_type.name,
        "field_of_view": float(c.field_of_view),
        "orthographic_height": float(c.orthographic_height),
        "focus_distance": float(c.focus_distance),
    }


def _restore(data):
    c = _camera()
    c.projection_type = getattr(display.CameraProjectionType, data["projection"])
    c.position = [float(v) for v in data["position"]]
    c.rotation = [float(v) for v in data["rotation"]]
    if data["projection"] == "Orthographic":
        c.orthographic_height = float(data["orthographic_height"])
    else:
        c.field_of_view = float(data["field_of_view"])
    if "focus_distance" in data:
        c.focus_distance = float(data["focus_distance"])


def _settings():
    return QtCore.QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _get_region():
    """Return the saved viewport rectangle in global, logical screen pixels."""
    value = _settings().value("viewport_rect", "")
    if not value:
        return None
    try:
        numbers = json.loads(value)
        if (isinstance(numbers, list) and len(numbers) == 4
                and all(isinstance(n, int) for n in numbers)
                and numbers[2] >= 20 and numbers[3] >= 20):
            return QtCore.QRect(*numbers)
    except (ValueError, TypeError):
        pass
    return None


def _set_region(rect):
    _settings().setValue("viewport_rect", json.dumps([
        rect.x(), rect.y(), rect.width(), rect.height()
    ]))


def _output_dir():
    saved = _settings().value("output_dir", "", type=str)
    if saved and os.path.isdir(saved):
        return saved
    pictures = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.PicturesLocation
    )
    return pictures if pictures and os.path.isdir(pictures) else os.path.expanduser("~")


def _filename_base(value):
    """Sanitize an optional custom filename for Windows, preserving Unicode."""
    text = str(value or "").strip()
    for suffix in ('.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.tga','.exr','.ppm','.xbm','.xpm'):
        if text.lower().endswith(suffix):
            text=text[:-len(suffix)]
            break
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip(' .')
    text = text[:100].rstrip(' .')
    if not text:
        return ''
    if text.split('.', 1)[0].upper() in {
        'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10))
    }:
        text = '_' + text
    return text


def _new_png_path(directory, requested_name, kind):
    """Return a unique PNG path; user names are exact except for AllViews suffix."""
    base = _filename_base(requested_name)
    if base:
        stem = base + ('_AllViews' if kind == 'all' else '')
    else:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        stem = f'ViewAtlas_{"AllViews" if kind == "all" else "Viewport"}_{stamp}'
    path = os.path.join(directory, stem + '.png')
    suffix = 2
    while os.path.exists(path):
        path = os.path.join(directory, f'{stem}_{suffix:03d}.png')
        suffix += 1
    return path


def _available_image_formats():
    formats = []
    try:
        for raw in QtGui.QImageWriter.supportedImageFormats():
            fmt = bytes(raw).decode('ascii', 'ignore').lower()
            if fmt and fmt not in formats:
                formats.append(fmt)
    except Exception:
        formats = ['png', 'jpg', 'bmp']
    ordered = [f for f in _FORMAT_PREF_ORDER if f in formats]
    ordered.extend([f for f in formats if f not in ordered])
    return ordered or ['png']


def _sanitize_format(fmt):
    fmt = str(fmt or 'png').lower().strip('.')
    formats = _available_image_formats()
    return fmt if fmt in formats else ('png' if 'png' in formats else formats[0])


def _new_output_path(directory, requested_name, kind, fmt='png'):
    fmt = _sanitize_format(fmt)
    base = _filename_base(requested_name)
    if base:
        stem = base + ('_AllViews' if kind == 'all' else '')
    else:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        stem = f'ViewAtlas_{"AllViews" if kind == "all" else "Viewport"}_{stamp}'
    path = os.path.join(directory, stem + '.' + fmt)
    suffix = 2
    while os.path.exists(path):
        path = os.path.join(directory, f'{stem}_{suffix:03d}.' + fmt)
        suffix += 1
    return path


def _save_image_to_path(image, path, fmt):
    writer = QtGui.QImageWriter(path, fmt.upper().encode('ascii', 'ignore'))
    if fmt in ('jpg', 'jpeg', 'webp'):
        writer.setQuality(95)
    return writer.write(image)


def _lang_text(lang, ko, en):
    return ko if str(lang).startswith('ko') else en


def _slot_capture_mode(slot):
    return str(slot.get('capture_mode_v14', 'inherit')) if isinstance(slot, dict) else 'inherit'


def _active_stack_channel_order():
    default_order = ['basecolor', 'height', 'roughness', 'metallic', 'normal', 'emissive', 'opacity']
    if textureset is None:
        return default_order
    try:
        stack = textureset.get_active_stack()
        names = []
        for ch_type in stack.all_channels().keys():
            name = getattr(ch_type, 'name', str(ch_type)).lower()
            if name not in names:
                names.append(name)
        merged = [n for n in default_order if n in names] + [n for n in names if n not in default_order]
        return merged or default_order
    except Exception:
        return default_order


def _qt_object_alive(obj):
    """Check that a PySide wrapper still owns a live C++ Qt object."""
    if obj is None:
        return False
    try:
        if _shiboken_is_valid is not None and not _shiboken_is_valid(obj):
            return False
        obj.objectName()  # Calling an innocuous Qt method also detects dead wrappers.
        return True
    except (RuntimeError, ReferenceError):
        return False


def _send_shortcut_to_painter(key):
    """Best-effort Painter shortcut trigger with dead-Qt-object protection."""
    main = ui.get_main_window()
    region = _get_region()
    try:
        target = QtWidgets.QApplication.widgetAt(region.center()) if region is not None else None
        if not _qt_object_alive(target) or not main.isAncestorOf(target):
            target = main
    except (RuntimeError, ReferenceError):
        target = main
    for evtype in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
        if not _qt_object_alive(target):
            target = ui.get_main_window()
        event = QtGui.QKeyEvent(evtype, key, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(target, event)
    QtWidgets.QApplication.processEvents()


def _channel_combo_candidate():
    """Find a live Painter channel selector. Never return a known-dead wrapper.

    Painter can delete/recreate a QComboBox while switching viewport modes,
    so every interaction needs to tolerate C++ lifetime changes.
    """
    try:
        main = ui.get_main_window()
        found = []
        for combo in main.findChildren(QtWidgets.QComboBox):
            if not _qt_object_alive(combo):
                continue
            try:
                if not combo.isVisible():
                    continue
                length = combo.count()
                if length < 4:
                    continue
                values = [combo.itemText(i).lower().replace(' ', '').replace('_', '')
                          for i in range(length)]
                hits = sum(any(word in value for value in values)
                           for word in ('basecolor', 'roughness', 'metallic', 'normal'))
                if hits >= 3:
                    found.append((hits, combo))
            except (RuntimeError, ReferenceError):
                continue
        for _hits, combo in sorted(found, key=lambda item: item[0], reverse=True):
            if _qt_object_alive(combo):
                return combo
    except (RuntimeError, ReferenceError):
        pass
    return None


def _display_state_snapshot():
    """Save only plain Python data, NOT a pointer to Painter's changing combo."""
    combo = _channel_combo_candidate()
    if not _qt_object_alive(combo):
        return None
    try:
        text = str(combo.currentText())
        index = int(combo.currentIndex())
        return (text, index) if text and index >= 0 else None
    except (RuntimeError, ReferenceError):
        return None


def _restore_display_snapshot(snapshot):
    """Find a NEW control at restoration time; an old one may be deleted."""
    if not snapshot:
        return
    text, _old_index = snapshot
    combo = _channel_combo_candidate()
    if not _qt_object_alive(combo):
        return
    try:
        for index in range(combo.count()):
            if combo.itemText(index) == text:
                if _qt_object_alive(combo):
                    combo.setCurrentIndex(index)
                return
    except (RuntimeError, ReferenceError):
        # Painter may recreate the selector during the call. Safely do nothing.
        return


def _set_viewport_mode_experimental(mode):
    """Attempt direct channel selection; use Painter's M/C shortcut fallback.

    Public Painter Python API lacks a stable viewport channel setter. This is
    experimental; the host's UI and custom shortcut setups can behave differently.
    """
    mode = str(mode or 'current').lower()
    if mode == 'current':
        return
    aliases = {
        'basecolor': ['basecolor', 'basecolour', '기본색', '베이스컬러'],
        'roughness': ['roughness', '거칠기', '러프니스'],
        'metallic': ['metallic', 'metalness', '메탈릭', '금속'],
        'normal': ['normal', '노말'],
        'material': ['material', '머티리얼', '재질'],
    }
    combo = _channel_combo_candidate()
    if _qt_object_alive(combo):
        try:
            # Read values BEFORE selecting; selection may destroy this QComboBox.
            choices = [(i, combo.itemText(i).lower().replace(' ', '').replace('_', ''))
                       for i in range(combo.count())]
        except (RuntimeError, ReferenceError):
            choices = []
        for idx, label in choices:
            if any(label == alias or label.startswith(alias)
                   for alias in aliases.get(mode, [])):
                try:
                    if _qt_object_alive(combo):
                        combo.setCurrentIndex(idx)
                        return
                except (RuntimeError, ReferenceError):
                    # It may have been recreated because the selection succeeded.
                    fresh = _channel_combo_candidate()
                    if _qt_object_alive(fresh):
                        try:
                            current = fresh.currentText().lower().replace(' ', '').replace('_', '')
                            if any(current == alias or current.startswith(alias)
                                   for alias in aliases.get(mode, [])):
                                return
                        except (RuntimeError, ReferenceError):
                            pass
                    break
    if mode == 'material':
        _send_shortcut_to_painter(QtCore.Qt.Key_M)
        return
    order = _active_stack_channel_order()
    if mode not in order:
        raise RuntimeError('Channel not available in active Texture Set: ' + mode)
    _send_shortcut_to_painter(QtCore.Qt.Key_M)
    # Sequence is approximate because default channel order is not public API.
    for _ in range(order.index(mode) + 1):
        _send_shortcut_to_painter(QtCore.Qt.Key_C)


def _on_app_state_changed(state):
    try:
        if state == QtCore.Qt.ApplicationActive:
            _restore_outline()
        else:
            _hide_outline()
    except Exception as e:
        print('[ViewAtlas] App state:', repr(e))


def _ensure_app_state_signal():
    global _app_state_connected
    if _app_state_connected:
        return
    try:
        QtGui.QGuiApplication.instance().applicationStateChanged.connect(_on_app_state_changed)
        _app_state_connected = True
    except Exception as e:
        print('[ViewAtlas] App-state signal connect failed:', repr(e))


def _is_pinned_mode():
    return str(_settings().value("pinned_mode_v9", "false")).lower() == "true"


def _set_pinned_mode(value):
    _settings().setValue("pinned_mode_v9", "true" if value else "false")


def _host_widget():
    global _dock, _standalone
    return _standalone if _standalone is not None else _dock


def _hide_host():
    host = _host_widget()
    if host is not None:
        host.hide()


def _show_host():
    host = _host_widget()
    if host is not None:
        host.show()
        host.raise_()
        try:
            host.activateWindow()
        except Exception:
            pass


def _destroy_dock():
    global _widget, _dock, _standalone
    if _widget is not None and _standalone is None:
        try:
            _widget.cancel_batch()
        except Exception:
            pass
    if _widget is not None and _dock is not None:
        try:
            ui.delete_ui_element(_widget)
        except Exception:
            try:
                _widget.close()
                _widget.deleteLater()
            except Exception:
                pass
    _widget = None
    _dock = None


def _destroy_standalone():
    global _standalone
    if _standalone is not None:
        try:
            _standalone.cancel_batch()
        except Exception:
            pass
        try:
            _standalone.close()
            _standalone.deleteLater()
        except Exception:
            pass
    _standalone = None


def _schedule_switch_mode(pinned):
    _set_pinned_mode(pinned)
    QtCore.QTimer.singleShot(0, lambda: show_bookmarks(pinned))


class ViewportRegionSelector(QtWidgets.QWidget):
    """Overlay for selecting only the visible 3D viewport, not the Painter UI."""

    def __init__(self, main_window, on_done):
        super().__init__(None)
        self.on_done = on_done
        self._lang = _current_language()
        self._start = None
        self._current = None
        self.setWindowTitle(_tr("selector_title", self._lang))
        self.setWindowFlags(
            QtCore.Qt.Tool |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        # Cover the Painter main window, no guessing fragile private QWidget names.
        self.setGeometry(main_window.frameGeometry())

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 80))
        if self._start is not None and self._current is not None:
            rect = QtCore.QRect(self._start, self._current).normalized()
            p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
            p.fillRect(rect, QtCore.Qt.transparent)
            p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
            p.setPen(QtGui.QPen(QtGui.QColor(80, 205, 255), 2))
            p.drawRect(rect)
            p.setPen(QtCore.Qt.white)
            p.drawText(rect.adjusted(6, 6, -6, -6),
                       QtCore.Qt.AlignTop,
                       f"{rect.width()} x {rect.height()}")
        p.setPen(QtCore.Qt.white)
        p.setFont(QtGui.QFont("Segoe UI", 12, QtGui.QFont.Bold))
        p.drawText(self.rect().adjusted(15, 14, -15, -14),
                   QtCore.Qt.AlignTop |
                   QtCore.Qt.AlignHCenter,
                   _tr("selector_help", self._lang))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._start = event.pos()
            self._current = self._start
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self._start is None:
            return
        rect = QtCore.QRect(self._start, event.pos()).normalized()
        if rect.width() < 50 or rect.height() < 50:
            self._start = None
            self._current = None
            self.update()
            return
        global_rect = QtCore.QRect(self.mapToGlobal(rect.topLeft()), rect.size())
        self.close()
        self.on_done(global_rect)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
            self.on_done(None)
        else:
            super().keyPressEvent(event)




# V13 UI: concise labels; all languages supported with English fallback for new labels.
_V13 = {
'en': dict(tab_main='Workspace', tab_preview='Previews', tab_settings='Settings', pin_short='Pin', views_short='Camera views', all_short='All', none_short='None',
            capture_short='Capture', select_short='Set area', outline_short='Outline', png_short='Save PNG', batch_short='Capture selected + merge',
            filename_short='Filename', output_short='Save folder', open_short='Open after save', change_short='Browse', saved_count='Slots',
            gallery_short='Gallery', single_short='Single', no_thumb='No preview', preview_tip='A thumbnail is made when saving a camera slot. Select a capture region first.',
            selected_tip='Check the camera slots to include in the combined screenshot.', preview_mode_tip='Preview every saved camera or inspect one thumbnail at a time.',

            layout_short='Arrangement', gap_short='Spacing', crop_short='Center crop (1:2)', delay_short='Camera wait',
            resolution_short='PNG output size', resolution_mode='Size', native_short='Original', custom_short='Custom W × H',
            size_note='2×/3×/4× & custom use image interpolation, not true high-resolution rendering.',
            export_group='Reuse in other projects', export_short='Export JSON', import_short='Import JSON',
            export_tip='Exports up to 10 camera views, thumbnails, selection flags and capture-size preferences. Local save-folder paths are excluded.',
            import_tip='Imports camera views and capture settings into the open project. This replaces existing camera slots. Save the project afterward.',
            replace_confirm='Replace the camera bookmarks and capture settings in this project with the imported file?',
            file_exported='Settings exported: {path}', file_imported='Imported views and settings. Save the .spp project.',
            invalid_file='Invalid ViewAtlas JSON file: {error}', no_project='Open a project first.',
            region_mismatch='Capture region is outside your current monitors. Select the area again.',
            tooltip_pin='Detached always-on-top window. Tab visibility depends on Painter and Windows.',
            tooltip_area='Drag the exact 3D viewport area to capture. The selection is saved on this computer.',
            tooltip_outline='Keep a thin click-through border visible while working. It is hidden during capture.',
            tooltip_capture='Save the current on-screen viewport as PNG.', tooltip_batch='Capture checked saved cameras and combine into one PNG.',
            tooltip_size='Resizes captured on-screen pixels using smooth interpolation, without creating new model detail.',
            tooltip_name='Optional name. Empty uses a timestamp; existing files are not overwritten.',
            tooltip_folder='Choose where screenshots are saved. This path stays local.',
            tooltip_delay='Time allowed for Painter to update after restoring each camera.',
            tooltip_crop='Optional centered 1:2 crop; leave off to keep the original screenshot aspect ratio.',
            tooltip_refresh='Reload saved camera views from the current project.',
            no_selection='No saved, checked camera views. Check at least one view.',
            overlay_failed='Could not display the overlay: {error}',
            output_size_tip='Custom dimensions are a maximum bounding box. Aspect ratio remains unchanged.',
            next_short='Next', previous_short='Previous',
            status_ready='Ready', settings_saved='Settings saved', no_area='Area not set'),
'ko': dict(tab_main='주요 기능', tab_preview='미리보기', tab_settings='설정', pin_short='창 고정', views_short='카메라 뷰', all_short='전체', none_short='해제',
           capture_short='스크린샷', select_short='영역 지정', outline_short='테두리', png_short='PNG 저장', batch_short='선택 뷰 촬영·합치기',
           filename_short='파일명', output_short='저장 위치', open_short='저장 후 열기', change_short='변경', saved_count='슬롯',
           gallery_short='전체 보기', single_short='개별 보기', no_thumb='미리보기 없음', preview_tip='영역을 지정한 다음 뷰를 저장하면 미리보기가 생성됩니다.',
           selected_tip='합쳐서 촬영할 뷰만 체크하세요.', preview_mode_tip='저장된 뷰를 한 번에 보거나 하나씩 크게 확인합니다.',

           layout_short='배치', gap_short='간격', crop_short='중앙 자르기 (1:2)', delay_short='카메라 대기',
           resolution_short='PNG 출력 크기', resolution_mode='크기', native_short='원본', custom_short='직접 입력 W × H',
           size_note='2~4배·직접 입력은 보간 확대이며 실제 고해상도 렌더가 아닙니다.',
           export_group='다른 프로젝트에서 재사용', export_short='JSON 내보내기', import_short='JSON 가져오기',
           export_tip='최대 10개 뷰, 썸네일, 촬영 선택 상태와 캡처/해상도 설정을 내보냅니다. 로컬 폴더 경로는 제외합니다.',
           import_tip='현재 프로젝트의 카메라 뷰와 촬영 설정을 파일 내용으로 교체합니다. 완료 후 프로젝트를 저장하세요.',
           replace_confirm='현재 프로젝트의 카메라 뷰와 촬영 설정을 파일 내용으로 교체할까요?',
           file_exported='설정 내보내기 완료: {path}', file_imported='뷰·설정 가져오기 완료. .spp 프로젝트를 저장하세요.',
           invalid_file='잘못된 ViewAtlas JSON 파일: {error}', no_project='먼저 프로젝트를 열어 주세요.',
           region_mismatch='촬영 영역이 현재 모니터 바깥에 있습니다. 영역을 다시 지정하세요.',
           tooltip_pin='독립된 항상-위 창으로 표시합니다. Tab 모드 유지는 Painter/Windows 동작에 따라 달라집니다.',
           tooltip_area='3D 뷰포트에서 실제 촬영할 영역을 드래그합니다. 영역은 현재 컴퓨터에 저장됩니다.',
           tooltip_outline='작업을 방해하지 않는 클릭 통과 테두리를 계속 표시합니다. 촬영 시에는 자동 숨김됩니다.',
           tooltip_capture='지금 화면에 보이는 뷰포트를 PNG로 저장합니다.', tooltip_batch='체크한 카메라를 차례로 촬영해 한 장의 PNG로 합칩니다.',
           tooltip_size='화면에서 캡처한 픽셀을 보간 확대합니다. 실제 모델 디테일이 추가되지는 않습니다.',
           tooltip_name='비우면 날짜 기반 이름으로 저장. 같은 파일은 덮어쓰지 않습니다.',
           tooltip_folder='PNG 저장 폴더입니다. 다른 PC로 내보내지는 않습니다.',
           tooltip_delay='각 카메라 시점으로 이동한 뒤 Painter가 화면을 갱신할 시간입니다.',
           tooltip_crop='가운데 부분만 1:2로 자릅니다. 끄면 원본 화면 비율을 유지합니다.',
           tooltip_refresh='현재 프로젝트에서 카메라 저장 정보를 다시 읽습니다.',
           no_selection='체크된 카메라가 없습니다. 저장된 뷰 중 하나 이상 선택하세요.',
           overlay_failed='테두리를 표시하지 못했습니다: {error}',
           output_size_tip='직접 입력한 너비와 높이 안에 비율을 유지해 맞춥니다.',
           next_short='다음', previous_short='이전', status_ready='준비됨', settings_saved='설정 저장됨', no_area='영역 미설정'),
'ja': dict(tab_main='メイン',tab_preview='プレビュー',tab_settings='設定',pin_short='固定',views_short='カメラビュー',all_short='全て',none_short='解除',capture_short='撮影',select_short='範囲指定',outline_short='枠表示',png_short='PNG保存',batch_short='選択ビューを結合',filename_short='ファイル名',output_short='保存先',open_short='保存後開く',change_short='変更',saved_count='スロット',gallery_short='一覧',single_short='個別',no_thumb='プレビューなし',layout_short='配置',gap_short='間隔',crop_short='中央1:2トリム',delay_short='描画待機',resolution_short='PNG出力サイズ',resolution_mode='サイズ',native_short='元画像',custom_short='カスタム W × H',size_note='拡大は補間処理で、高解像度レンダリングではありません。',export_group='別プロジェクトで再利用',export_short='JSON書き出し',import_short='JSON読み込み',replace_confirm='現在のビューと設定を置き換えますか？',file_imported='読み込み完了。.spp を保存してください。'),
'zh_CN': dict(tab_main='主要功能',tab_preview='预览',tab_settings='设置',pin_short='置顶',views_short='相机视图',all_short='全选',none_short='全不选',capture_short='截图',select_short='选择区域',outline_short='显示边框',png_short='保存PNG',batch_short='合并所选视图',filename_short='文件名',output_short='保存位置',open_short='保存后打开',change_short='更改',saved_count='数量',gallery_short='网格查看',single_short='单张查看',no_thumb='无预览',layout_short='布局',gap_short='间距',crop_short='中央裁剪1:2',delay_short='渲染等待',resolution_short='PNG输出尺寸',resolution_mode='尺寸',native_short='原始',custom_short='自定义 W × H',size_note='放大采用插值，并非真正高分辨率渲染。',export_group='跨项目复用',export_short='导出JSON',import_short='导入JSON',replace_confirm='替换当前项目的视图和设置吗？',file_imported='导入成功，请保存 .spp 项目。'),
'zh_TW': dict(tab_main='主要功能',tab_preview='預覽',tab_settings='設定',pin_short='置頂',views_short='相機視角',all_short='全選',none_short='全不選',capture_short='截圖',select_short='選取範圍',outline_short='顯示框線',png_short='儲存PNG',batch_short='合併已選視角',filename_short='檔名',output_short='儲存位置',open_short='儲存後開啟',change_short='更改',saved_count='數量',gallery_short='全部檢視',single_short='單張檢視',no_thumb='沒有預覽',layout_short='排列',gap_short='間距',crop_short='中央裁切1:2',delay_short='渲染等待',resolution_short='PNG輸出尺寸',resolution_mode='尺寸',native_short='原始',custom_short='自訂 W × H',size_note='放大使用插值，並非真正的高解析度渲染。',export_group='跨專案重用',export_short='匯出JSON',import_short='匯入JSON',replace_confirm='取代目前專案的視角與設定嗎？',file_imported='匯入成功，請儲存 .spp 專案。'),
'es': dict(tab_main='Principal',tab_preview='Vistas previas',tab_settings='Ajustes',pin_short='Fijar',views_short='Cámaras',all_short='Todos',none_short='Ninguno',capture_short='Captura',select_short='Área',outline_short='Borde',png_short='Guardar PNG',batch_short='Combinar vistas',filename_short='Archivo',output_short='Carpeta',open_short='Abrir al guardar',change_short='Cambiar',saved_count='Ranuras',gallery_short='Galería',single_short='Individual',no_thumb='Sin vista previa',layout_short='Diseño',gap_short='Espacio',crop_short='Recorte central 1:2',delay_short='Espera',resolution_short='Tamaño de PNG',resolution_mode='Tamaño',native_short='Original',custom_short='Personalizado W × H',size_note='La ampliación usa interpolación; no es un render real de alta resolución.',export_group='Reutilizar en otros proyectos',export_short='Exportar JSON',import_short='Importar JSON',replace_confirm='¿Reemplazar vistas y ajustes actuales?',file_imported='Importado. Guarda el proyecto .spp.'),
'fr': dict(tab_main='Principal',tab_preview='Aperçus',tab_settings='Paramètres',pin_short='Épingler',views_short='Vues caméra',all_short='Toutes',none_short='Aucune',capture_short='Capture',select_short='Zone',outline_short='Contour',png_short='Enregistrer PNG',batch_short='Fusionner les vues',filename_short='Nom du fichier',output_short='Dossier',open_short='Ouvrir après',change_short='Modifier',saved_count='Emplacements',gallery_short='Galerie',single_short='Individuel',no_thumb='Aucun aperçu',layout_short='Disposition',gap_short='Espacement',crop_short='Recadrage 1:2',delay_short='Attente',resolution_short='Taille PNG',resolution_mode='Taille',native_short='Original',custom_short='Personnalisé W × H',size_note='L’agrandissement interpole les pixels ; ce n’est pas un rendu haute résolution.',export_group='Réutiliser ailleurs',export_short='Exporter JSON',import_short='Importer JSON',replace_confirm='Remplacer les vues et réglages actuels ?',file_imported='Importé. Enregistrez le projet .spp.'),
'de': dict(tab_main='Hauptfunktionen',tab_preview='Vorschau',tab_settings='Einstellungen',pin_short='Anheften',views_short='Kameraansichten',all_short='Alle',none_short='Keine',capture_short='Aufnahme',select_short='Bereich',outline_short='Rahmen',png_short='PNG speichern',batch_short='Ansichten zusammenfügen',filename_short='Dateiname',output_short='Ordner',open_short='Nachher öffnen',change_short='Ändern',saved_count='Slots',gallery_short='Galerie',single_short='Einzeln',no_thumb='Keine Vorschau',layout_short='Anordnung',gap_short='Abstand',crop_short='Mitte zuschneiden 1:2',delay_short='Wartezeit',resolution_short='PNG-Ausgabegröße',resolution_mode='Größe',native_short='Original',custom_short='Benutzerdefiniert W × H',size_note='Vergrößerung interpoliert Pixel; kein echtes hochauflösendes Rendering.',export_group='In anderen Projekten nutzen',export_short='JSON exportieren',import_short='JSON importieren',replace_confirm='Aktuelle Ansichten und Einstellungen ersetzen?',file_imported='Importiert. Projekt .spp speichern.'),
'pt': dict(tab_main='Principal',tab_preview='Prévia',tab_settings='Configurações',pin_short='Fixar',views_short='Câmeras',all_short='Todas',none_short='Nenhuma',capture_short='Captura',select_short='Área',outline_short='Contorno',png_short='Salvar PNG',batch_short='Mesclar vistas',filename_short='Arquivo',output_short='Pasta',open_short='Abrir ao salvar',change_short='Alterar',saved_count='Slots',gallery_short='Galeria',single_short='Individual',no_thumb='Sem prévia',layout_short='Arranjo',gap_short='Espaço',crop_short='Recortar centro 1:2',delay_short='Espera',resolution_short='Tamanho PNG',resolution_mode='Tamanho',native_short='Original',custom_short='Personalizado W × H',size_note='A ampliação usa interpolação; não é renderização de alta resolução.',export_group='Reusar em projetos',export_short='Exportar JSON',import_short='Importar JSON',replace_confirm='Substituir vistas e configurações?',file_imported='Importado. Salve o projeto .spp.'),
'ru': dict(tab_main='Главное',tab_preview='Предпросмотр',tab_settings='Настройки',pin_short='Закрепить',views_short='Камеры',all_short='Все',none_short='Снять',capture_short='Снимок',select_short='Область',outline_short='Рамка',png_short='Сохранить PNG',batch_short='Объединить виды',filename_short='Имя файла',output_short='Папка',open_short='Открыть после',change_short='Изменить',saved_count='Слоты',gallery_short='Галерея',single_short='Один вид',no_thumb='Нет предпросмотра',layout_short='Расположение',gap_short='Отступ',crop_short='Центр 1:2',delay_short='Пауза',resolution_short='Размер PNG',resolution_mode='Размер',native_short='Оригинал',custom_short='Свой W × H',size_note='Увеличение использует интерполяцию, не настоящий рендер высокого разрешения.',export_group='Для других проектов',export_short='Экспорт JSON',import_short='Импорт JSON',replace_confirm='Заменить виды и настройки?',file_imported='Импортировано. Сохраните проект .spp.'),
'it': dict(tab_main='Principale',tab_preview='Anteprime',tab_settings='Impostazioni',pin_short='Blocca',views_short='Viste camera',all_short='Tutte',none_short='Nessuna',capture_short='Schermata',select_short='Area',outline_short='Bordo',png_short='Salva PNG',batch_short='Unisci viste',filename_short='Nome file',output_short='Cartella',open_short='Apri dopo',change_short='Cambia',saved_count='Slot',gallery_short='Galleria',single_short='Singola',no_thumb='Nessuna anteprima',layout_short='Disposizione',gap_short='Spazio',crop_short='Ritaglio centrale 1:2',delay_short='Attesa',resolution_short='Dimensioni PNG',resolution_mode='Dimensioni',native_short='Originale',custom_short='Personalizzato W × H',size_note='L’ingrandimento interpola i pixel: non è un rendering ad alta risoluzione.',export_group='Riutilizza in altri progetti',export_short='Esporta JSON',import_short='Importa JSON',replace_confirm='Sostituire viste e impostazioni correnti?',file_imported='Importato. Salva il progetto .spp.')
}
for _locale, _data in _V13.items():
    _TRANSLATIONS[_locale].update(_data)
del _locale, _data


def _setting_bool(key, default=False):
    return str(_settings().value(key, 'true' if default else 'false')).lower() == 'true'


def _safe_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError):
        return default


def _grab_viewport(rect):
    screen = QtGui.QGuiApplication.screenAt(rect.center())
    if screen is None:
        raise RuntimeError(_tr('no_screen'))
    bounds = screen.geometry()
    if not bounds.contains(rect):
        raise RuntimeError(_tr('outside'))
    pm = screen.grabWindow(0, rect.x()-bounds.x(), rect.y()-bounds.y(), rect.width(), rect.height())
    if pm.isNull():
        raise RuntimeError(_tr('grab_fail'))
    image = pm.toImage().copy()
    image.setDevicePixelRatio(1.0)
    return image


def _validate_camera(record):
    if not isinstance(record, dict):
        raise ValueError('camera is not an object')
    result = {}
    for key in ('position', 'rotation'):
        v = record.get(key)
        if not isinstance(v, list) or (len(v) != 3 if key == 'position' else len(v) not in (3, 4)):
            raise ValueError('invalid camera ' + key)
        values = [float(n) for n in v]
        if not all(math.isfinite(n) and abs(n) <= 1e12 for n in values):
            raise ValueError('non-finite camera ' + key)
        result[key] = values
    proj = record.get('projection')
    if not isinstance(proj, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', proj):
        raise ValueError('invalid camera projection')
    if not hasattr(display.CameraProjectionType, proj):
        raise ValueError('unsupported camera projection: ' + proj)
    result['projection'] = proj
    for key in ('field_of_view', 'orthographic_height', 'focus_distance'):
        number = float(record.get(key, 1))
        if not math.isfinite(number) or not (0 < number < 1e12):
            raise ValueError('invalid camera ' + key)
        result[key] = number
    return result


def _validate_import(data):
    if not isinstance(data, dict) or data.get('format') != 'ViewAtlas' or data.get('schema') != 1:
        raise ValueError('unknown format or schema')
    input_slots = data.get('slots')
    if not isinstance(input_slots, list) or len(input_slots) > _NUM_SLOTS:
        raise ValueError('camera slots must be a list with at most 10 entries')
    slots = []
    for item in input_slots:
        if item is None:
            slots.append(None)
            continue
        if not isinstance(item, dict):
            raise ValueError('invalid slot')
        name = str(item.get('name', 'View'))[:100]
        entry = {'name':name, 'camera':_validate_camera(item.get('camera')), 'capture_mode_v14': str(item.get('capture_mode_v14', 'inherit'))}
        thumb = item.get('thumbnail_jpeg_v12', '')
        if thumb:
            if not isinstance(thumb, str) or len(thumb) > 1_200_000:
                raise ValueError('thumbnail too large')
            raw = base64.b64decode(thumb, validate=True)
            if not raw.startswith(b'\xff\xd8'):
                raise ValueError('invalid JPEG thumbnail')
            entry['thumbnail_jpeg_v12'] = thumb
        slots.append(entry)
    slots = (slots + [None] * _NUM_SLOTS)[:_NUM_SLOTS]
    flags = data.get('selected', [True]*_NUM_SLOTS)
    if not isinstance(flags, list):
        raise ValueError('invalid selected slots')
    selections = [bool(x) for x in (flags+[True]*_NUM_SLOTS)[:_NUM_SLOTS]]
    opts = data.get('settings', {})
    if not isinstance(opts, dict):
        raise ValueError('invalid settings')
    cleaned = {
        'visible_slots': _safe_int(opts.get('visible_slots'), 6, 1, 10),
        'collage_layout': _safe_int(opts.get('collage_layout'), 0, 0, 2),
        'collage_gap': _safe_int(opts.get('collage_gap'), 0, 0, 60),
        'collage_delay_ms': _safe_int(opts.get('collage_delay_ms'), 1200, 300, 4000),
        'center_crop': bool(opts.get('center_crop', False)),
        'sizing_mode': '1x',
        'sizing_width': _safe_int(opts.get('sizing_width'), 1920, 64, 8192),
        'sizing_height': _safe_int(opts.get('sizing_height'), 1080, 64, 8192),
        'output_format': _sanitize_format(opts.get('output_format', 'png')),
        'global_capture_mode': str(opts.get('global_capture_mode', 'current')),
    }
    if cleaned['global_capture_mode'] not in {k for k, _ in _CHANNEL_MODE_ITEMS}:
        cleaned['global_capture_mode'] = 'current'
    raw_rect = opts.get('capture_rect')
    region = None
    if isinstance(raw_rect, list) and len(raw_rect) == 4:
        try:
            nums = [int(n) for n in raw_rect]
            if (20 <= nums[2] <= 16384 and 20 <= nums[3] <= 16384
                and all(abs(n) < 1_000_000 for n in nums)):
                region = QtCore.QRect(*nums)
        except (ValueError, TypeError):
            pass
    return slots, selections, cleaned, region


class PersistentCaptureOutline(QtWidgets.QWidget):
    """Transparent, click-through on-screen border; does not block working in Painter."""
    def __init__(self, capture_rect):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.Tool |
                            QtCore.Qt.FramelessWindowHint |
                            QtCore.Qt.WindowStaysOnTopHint |
                            QtCore.Qt.WindowTransparentForInput |
                            QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.set_region(capture_rect)

    def set_region(self, rect):
        self.setGeometry(rect.adjusted(-2, -2, 2, 2))
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        try:
            p.setPen(QtGui.QPen(QtGui.QColor(55, 212, 230, 225), 1))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRect(self.rect().adjusted(2, 2, -3, -3))
        finally:
            p.end()


def _overlay_enabled():
    return _setting_bool('region_outline_v13', False)


def _update_global_outline():
    global _region_preview
    region = _get_region()
    if not _overlay_enabled() or region is None:
        if _region_preview is not None:
            _region_preview.hide()
            _region_preview.deleteLater()
            _region_preview = None
        return
    if QtGui.QGuiApplication.applicationState() != QtCore.Qt.ApplicationActive:
        if _region_preview is not None:
            _region_preview.hide()
        return
    if _region_preview is None:
        _region_preview = PersistentCaptureOutline(region)
    else:
        _region_preview.set_region(region)
    _region_preview.show()
    _region_preview.raise_()


def _hide_outline():
    if _region_preview is not None:
        _region_preview.hide()


def _restore_outline():
    if _overlay_enabled():
        _update_global_outline()


class CameraBookmarksPanel(QtWidgets.QWidget):
    def __init__(self, pinned_mode=False):
        super().__init__()
        self.pinned_mode = bool(pinned_mode)
        _ensure_app_state_signal()
        self._lang = _current_language()
        self._capture_busy = False
        self._selector_pending = False
        self._thumb_pending = None
        self._batch_state = None
        self.setObjectName('ViewAtlasPanelV15')
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(_brand_icon())
        self.setMinimumWidth(390)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(9, 7, 9, 8)
        root.setSpacing(5)

        # Compact global header, with language at far right.
        header = QtWidgets.QHBoxLayout()
        # Second user-provided logo: shown inside ViewAtlas, not the Windows file icon.
        self.brand_label = QtWidgets.QLabel()
        mark = _brand_mark()
        if not mark.isNull():
            small = mark.scaled(70, 37, QtCore.Qt.KeepAspectRatio,
                                QtCore.Qt.SmoothTransformation)
            self.brand_label.setPixmap(small)
        else:
            self.brand_label.setText('VA')
        self.brand_label.setFixedWidth(76)
        self.brand_label.setToolTip('ViewAtlas')
        header.addWidget(self.brand_label)
        self.pin_check = QtWidgets.QCheckBox()
        self.pin_check.setChecked(self.pinned_mode)
        self.pin_check.toggled.connect(self._on_pin_toggled)
        header.addWidget(self.pin_check)
        header.addStretch(1)
        self.language_combo = QtWidgets.QComboBox()
        self.language_combo.setFixedWidth(108)
        for code, native in _LANGUAGES:
            self.language_combo.addItem(native, code)
        idx = self.language_combo.findData(_language_setting())
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        header.addWidget(self.language_combo)
        root.addLayout(header)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(QtCore.Qt.ElideRight)
        self.main_tab = QtWidgets.QWidget()
        self.preview_tab = QtWidgets.QWidget()
        self.settings_tab = QtWidgets.QWidget()
        for tab in (self.main_tab, self.preview_tab, self.settings_tab):
            self.tabs.addTab(tab, '')
        # Show the requested in-app mark as the icon on the main tab.
        mark = _brand_mark()
        if not mark.isNull():
            self.tabs.setTabIcon(0, QtGui.QIcon(mark))
        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda idx: _settings().setValue('active_tab_v13', idx))

        # Main tab: only frequent actions.
        main = QtWidgets.QVBoxLayout(self.main_tab)
        main.setContentsMargins(3, 8, 3, 2)
        main.setSpacing(7)
        self.views_group = QtWidgets.QGroupBox()
        views = QtWidgets.QVBoxLayout(self.views_group)
        views.setContentsMargins(7, 10, 7, 7)
        views.setSpacing(4)
        view_tools = QtWidgets.QHBoxLayout()
        self.slot_count_label = QtWidgets.QLabel()
        view_tools.addWidget(self.slot_count_label)
        self.slot_count_spin = QtWidgets.QSpinBox()
        self.slot_count_spin.setRange(1, _NUM_SLOTS)
        self.slot_count_spin.setValue(_safe_int(_settings().value('visible_slots', 6), 6, 1, 10))
        self.slot_count_spin.setFixedWidth(53)
        view_tools.addWidget(self.slot_count_spin)
        view_tools.addStretch(1)
        self.select_all_button = QtWidgets.QPushButton()
        self.select_none_button = QtWidgets.QPushButton()
        self.select_all_button.clicked.connect(lambda: self._select_all_slots(True))
        self.select_none_button.clicked.connect(lambda: self._select_all_slots(False))
        for b in (self.select_all_button, self.select_none_button):
            b.setFixedWidth(51)
            view_tools.addWidget(b)
        views.addLayout(view_tools)

        self.edits = []
        self.jump_buttons = []
        self.save_buttons = []
        self.slot_rows = []
        self.slot_checks = []
        self.preview_images = []
        self.gallery_names = []
        self.gallery_frames = []
        self.slot_container = QtWidgets.QWidget()
        slot_layout = QtWidgets.QVBoxLayout(self.slot_container)
        slot_layout.setContentsMargins(1, 1, 1, 1)
        slot_layout.setSpacing(3)
        for i in range(_NUM_SLOTS):
            row_widget = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            check = QtWidgets.QCheckBox()
            check.setChecked(True)
            check.toggled.connect(lambda v, index=i: self._toggle_slot_selection(index,v))
            row.addWidget(check)
            number = QtWidgets.QLabel(str(i+1))
            number.setFixedWidth(13)
            row.addWidget(number)
            edit = QtWidgets.QLineEdit(self.t('view',n=i+1))
            edit.setMinimumWidth(70)
            edit.editingFinished.connect(lambda index=i: self.rename_slot(index))
            row.addWidget(edit, 1)
            save = QtWidgets.QPushButton()
            jump = QtWidgets.QPushButton()
            for b in (save, jump):
                b.setFixedWidth(51)
            save.clicked.connect(lambda _=False, index=i: self.save_slot(index))
            jump.clicked.connect(lambda _=False, index=i: self.restore_slot(index))
            row.addWidget(save)
            row.addWidget(jump)
            slot_layout.addWidget(row_widget)
            self.slot_rows.append(row_widget)
            self.slot_checks.append(check)
            self.edits.append(edit)
            self.save_buttons.append(save)
            self.jump_buttons.append(jump)

        self.slot_scroll = QtWidgets.QScrollArea()
        self.slot_scroll.setWidgetResizable(True)
        self.slot_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.slot_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.slot_scroll.setWidget(self.slot_container)
        views.addWidget(self.slot_scroll)
        self.slot_count_spin.valueChanged.connect(self._set_slot_count)
        self._set_slot_count(self.slot_count_spin.value())
        main.addWidget(self.views_group)

        self.capture_group = QtWidgets.QGroupBox()
        capture = QtWidgets.QVBoxLayout(self.capture_group)
        capture.setContentsMargins(7, 10, 7, 7)
        capture.setSpacing(5)
        capture_buttons = QtWidgets.QHBoxLayout()
        capture_buttons.setSpacing(4)
        self.region_button = QtWidgets.QPushButton()
        self.region_button.clicked.connect(self.select_region)
        self.outline_check = QtWidgets.QCheckBox()
        self.outline_check.setChecked(_overlay_enabled())
        self.outline_check.toggled.connect(self._on_outline_toggled)
        self.capture_button = QtWidgets.QPushButton()
        self.capture_button.clicked.connect(self.save_screenshot)
        capture_buttons.addWidget(self.region_button, 1)
        capture_buttons.addWidget(self.outline_check)
        capture_buttons.addWidget(self.capture_button, 1)
        capture.addLayout(capture_buttons)
        self.capture_options = QtWidgets.QWidget()
        copts = QtWidgets.QGridLayout(self.capture_options)
        copts.setContentsMargins(0,0,0,0)
        copts.setHorizontalSpacing(4)
        copts.setVerticalSpacing(4)
        self.global_mode_label = QtWidgets.QLabel()
        self.global_mode_combo = QtWidgets.QComboBox()
        for key, text in _CHANNEL_MODE_ITEMS:
            self.global_mode_combo.addItem(text, key)
        self.global_mode_combo.setCurrentIndex(max(0, self.global_mode_combo.findData(str(_settings().value('global_capture_mode_v14', 'current')))))
        self.global_mode_combo.currentIndexChanged.connect(lambda idx: _settings().setValue('global_capture_mode_v14', self.global_mode_combo.itemData(idx)))
        copts.addWidget(self.global_mode_label, 0, 0)
        copts.addWidget(self.global_mode_combo, 0, 1)
        capture.addWidget(self.capture_options)
        self.batch_button = QtWidgets.QPushButton()
        self.batch_button.clicked.connect(self.save_batch_screenshot)
        capture.addWidget(self.batch_button)
        self.region_label = QtWidgets.QLabel()
        capture.addWidget(self.region_label)
        main.addWidget(self.capture_group)

        self.output_group = QtWidgets.QGroupBox()
        output = QtWidgets.QVBoxLayout(self.output_group)
        output.setContentsMargins(7, 10, 7, 7)
        output.setSpacing(5)
        filename_row = QtWidgets.QHBoxLayout()
        self.file_name_label = QtWidgets.QLabel()
        filename_row.addWidget(self.file_name_label)
        self.file_name_edit = QtWidgets.QLineEdit(str(_settings().value('capture_filename_v11','',type=str)))
        self.file_name_edit.textChanged.connect(lambda v: _settings().setValue('capture_filename_v11',v))
        filename_row.addWidget(self.file_name_edit,1)
        output.addLayout(filename_row)
        format_row = QtWidgets.QHBoxLayout()
        self.format_label = QtWidgets.QLabel()
        format_row.addWidget(self.format_label)
        self.format_combo = QtWidgets.QComboBox()
        for fmt in _available_image_formats():
            self.format_combo.addItem(fmt.upper(), fmt)
        default_fmt = _sanitize_format(_settings().value('output_format_v14', 'png', type=str))
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(default_fmt)))
        self.format_combo.currentIndexChanged.connect(lambda idx: _settings().setValue('output_format_v14', self.format_combo.itemData(idx)))
        format_row.addWidget(self.format_combo, 1)
        output.addLayout(format_row)
        path_row = QtWidgets.QHBoxLayout()
        self.folder_label = QtWidgets.QLabel()
        self.folder_label.setMinimumWidth(70)
        self.folder_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        path_row.addWidget(self.folder_label,1)
        self.browse_button = QtWidgets.QPushButton()
        self.browse_button.setFixedWidth(62)
        self.browse_button.clicked.connect(self.choose_folder)
        path_row.addWidget(self.browse_button)
        output.addLayout(path_row)
        self.open_after_check = QtWidgets.QCheckBox()
        self.open_after_check.setChecked(_setting_bool('auto_open_capture_v11', True))
        self.open_after_check.toggled.connect(lambda v: _settings().setValue('auto_open_capture_v11','true' if v else 'false'))
        output.addWidget(self.open_after_check)
        main.addWidget(self.output_group)
        main.addStretch(1)

        # Preview tab: gallery & individual review. Never force popup previews.
        preview_layout = QtWidgets.QVBoxLayout(self.preview_tab)
        preview_layout.setContentsMargins(3, 8, 3, 3)
        preview_layout.setSpacing(6)
        self.preview_mode = QtWidgets.QComboBox()
        self.preview_mode.addItems(['',''])
        self.preview_mode.currentIndexChanged.connect(self._change_preview_mode)
        preview_layout.addWidget(self.preview_mode)
        self.preview_stack = QtWidgets.QStackedWidget()
        preview_layout.addWidget(self.preview_stack,1)
        self.gallery_page = QtWidgets.QScrollArea()
        self.gallery_page.setWidgetResizable(True)
        self.gallery_page.setFrameShape(QtWidgets.QFrame.NoFrame)
        gallery_host = QtWidgets.QWidget()
        gallery_layout = QtWidgets.QGridLayout(gallery_host)
        gallery_layout.setContentsMargins(3, 3, 3, 3)
        gallery_layout.setSpacing(8)
        for i in range(_NUM_SLOTS):
            frame = QtWidgets.QFrame()
            frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
            frame_l = QtWidgets.QVBoxLayout(frame)
            frame_l.setContentsMargins(5, 5, 5, 5)
            frame_l.setSpacing(3)
            image_label = QtWidgets.QLabel('—')
            image_label.setAlignment(QtCore.Qt.AlignCenter)
            image_label.setFixedHeight(92)
            image_label.setMinimumWidth(118)
            image_label.setStyleSheet('QLabel{background:#24272d;color:#999;border:1px solid #484b52;}')
            name_label = QtWidgets.QLabel()
            name_label.setAlignment(QtCore.Qt.AlignCenter)
            frame_l.addWidget(image_label)
            frame_l.addWidget(name_label)
            gallery_layout.addWidget(frame,i//2,i%2)
            self.preview_images.append(image_label)
            self.gallery_names.append(name_label)
            self.gallery_frames.append(frame)
        gallery_layout.setRowStretch(5,1)
        self.gallery_page.setWidget(gallery_host)
        self.preview_stack.addWidget(self.gallery_page)

        single_page = QtWidgets.QWidget()
        single_layout = QtWidgets.QVBoxLayout(single_page)
        single_row = QtWidgets.QHBoxLayout()
        self.prev_button = QtWidgets.QPushButton('‹')
        self.next_button = QtWidgets.QPushButton('›')
        self.prev_button.setFixedWidth(34)
        self.next_button.setFixedWidth(34)
        self.prev_button.clicked.connect(lambda: self._step_single(-1))
        self.next_button.clicked.connect(lambda: self._step_single(1))
        self.single_combo = QtWidgets.QComboBox()
        for i in range(_NUM_SLOTS):
            self.single_combo.addItem(f'{i+1}', i)
        self.single_combo.currentIndexChanged.connect(self._refresh_single_preview)
        single_row.addWidget(self.prev_button)
        single_row.addWidget(self.single_combo,1)
        single_row.addWidget(self.next_button)
        single_layout.addLayout(single_row)
        self.single_image = QtWidgets.QLabel('—')
        self.single_image.setAlignment(QtCore.Qt.AlignCenter)
        self.single_image.setMinimumHeight(240)
        self.single_image.setStyleSheet('QLabel{background:#24272d;color:#999;border:1px solid #484b52;}')
        single_layout.addWidget(self.single_image,1)
        self.single_meta = QtWidgets.QLabel()
        self.single_meta.setAlignment(QtCore.Qt.AlignCenter)
        single_layout.addWidget(self.single_meta)
        self.single_options = QtWidgets.QGroupBox()
        so = QtWidgets.QFormLayout(self.single_options)
        so.setContentsMargins(8, 8, 8, 8)
        self.single_slot_mode_label = QtWidgets.QLabel()
        self.single_slot_mode = QtWidgets.QComboBox()
        self.single_slot_mode.addItem('Use global default', 'inherit')
        for key, text in _CHANNEL_MODE_ITEMS:
            self.single_slot_mode.addItem(text, key)
        self.single_slot_mode.currentIndexChanged.connect(self._save_selected_slot_options)
        so.addRow(self.single_slot_mode_label, self.single_slot_mode)
        single_layout.addWidget(self.single_options)
        self.preview_stack.addWidget(single_page)
        self._set_slot_count(self.slot_count_spin.value())  # Apply saved count to preview gallery too.
        self.preview_mode.setCurrentIndex(_safe_int(_settings().value('preview_mode_v13',0),0,0,1))

        # Settings tab, scrollable to preserve small window width/height.
        settings_outer = QtWidgets.QVBoxLayout(self.settings_tab)
        settings_outer.setContentsMargins(2, 7, 2, 2)
        settings_scroll = QtWidgets.QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        settings_outer.addWidget(settings_scroll)
        settings_host = QtWidgets.QWidget()
        settings = QtWidgets.QVBoxLayout(settings_host)
        settings.setContentsMargins(4,4,4,4)
        settings.setSpacing(8)
        settings_scroll.setWidget(settings_host)

        self.layout_group = QtWidgets.QGroupBox()
        lg = QtWidgets.QFormLayout(self.layout_group)
        lg.setContentsMargins(8,12,8,8)
        lg.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.layout_label = QtWidgets.QLabel()
        self.layout_combo = QtWidgets.QComboBox()
        self.layout_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.layout_combo.setMinimumContentsLength(11)
        self.layout_combo.addItems(['','',''])
        self.layout_combo.setCurrentIndex(_safe_int(_settings().value('collage_layout',0),0,0,2))
        self.layout_combo.currentIndexChanged.connect(lambda v: _settings().setValue('collage_layout',v))
        lg.addRow(self.layout_label,self.layout_combo)
        self.gap_label = QtWidgets.QLabel()
        self.gap_spin = QtWidgets.QSpinBox()
        self.gap_spin.setRange(0,60)
        self.gap_spin.setSuffix('px')
        self.gap_spin.setValue(_safe_int(_settings().value('collage_gap',0),0,0,60))
        self.gap_spin.valueChanged.connect(lambda v: _settings().setValue('collage_gap',v))
        lg.addRow(self.gap_label,self.gap_spin)
        self.delay_label = QtWidgets.QLabel()
        self.delay_spin = QtWidgets.QSpinBox()
        self.delay_spin.setRange(300,4000)
        self.delay_spin.setSingleStep(100)
        self.delay_spin.setSuffix('ms')
        self.delay_spin.setValue(_safe_int(_settings().value('collage_delay_ms',1200),1200,300,4000))
        self.delay_spin.valueChanged.connect(lambda v: _settings().setValue('collage_delay_ms',v))
        lg.addRow(self.delay_label,self.delay_spin)
        self.crop_check = QtWidgets.QCheckBox()
        self.crop_check.setChecked(_setting_bool('collage_center_crop_v7',False))
        self.crop_check.toggled.connect(lambda v: _settings().setValue('collage_center_crop_v7','true' if v else 'false'))
        lg.addRow(self.crop_check)
        settings.addWidget(self.layout_group)

        self.export_group = QtWidgets.QGroupBox()
        eg = QtWidgets.QHBoxLayout(self.export_group)
        self.export_button = QtWidgets.QPushButton()
        self.import_button = QtWidgets.QPushButton()
        self.export_button.clicked.connect(self.export_json)
        self.import_button.clicked.connect(self.import_json)
        eg.addWidget(self.export_button)
        eg.addWidget(self.import_button)
        settings.addWidget(self.export_group)
        self.refresh_button = QtWidgets.QPushButton()
        self.refresh_button.clicked.connect(self.refresh)
        settings.addWidget(self.refresh_button)
        settings.addStretch(1)

        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(28)
        self.status.setMaximumHeight(50)
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(self.status)
        # Deliberately no huge descriptive paragraphs in the UI; tooltips carry details.
        self.apply_language()
        self.tabs.setCurrentIndex(_safe_int(_settings().value('active_tab_v13',0),0,0,2))
        self.refresh()
        self._update_capture_labels()
        if self.outline_check.isChecked():
            try:
                _update_global_outline()
            except Exception as e:
                print('[ViewAtlas] Outline:',repr(e))

    def t(self, key, **kwargs):
        return _tr(key, self._lang, **kwargs)

    def _on_language_changed(self, index):
        code = self.language_combo.itemData(index)
        if code not in dict(_LANGUAGES):
            return
        _settings().setValue('ui_language_v10', code)
        self._lang = _current_language()
        self.apply_language()
        self._refresh_previews()

    def apply_language(self):
        self.setWindowTitle(APP_NAME)
        self.pin_check.setText(self.t('pin_short'))
        self.pin_check.setToolTip(self.t('tooltip_pin'))
        self.language_combo.setToolTip(self.t('language_auto_tip'))
        self.tabs.setTabText(0,self.t('tab_main'))
        self.tabs.setTabText(1,self.t('tab_preview'))
        self.tabs.setTabText(2,self.t('tab_settings'))
        # Never set a tooltip on the whole QTabWidget: child labels inherit it.
        self.tabs.setToolTip('')
        self.tabs.tabBar().setToolTip('')
        self.tabs.setTabToolTip(0, self.t('tab_main'))
        self.tabs.setTabToolTip(1, self.t('tab_preview'))
        self.tabs.setTabToolTip(2, self.t('tab_settings'))
        self.views_group.setTitle(self.t('views_short'))
        self.slot_count_label.setText(self.t('saved_count'))
        self.select_all_button.setText(self.t('all_short'))
        self.select_none_button.setText(self.t('none_short'))
        self.select_all_button.setToolTip(self.t('selected_tip'))
        self.select_none_button.setToolTip(self.t('selected_tip'))
        try:
            slots = _get_slots() if project.is_open() else [None]*_NUM_SLOTS
        except Exception:
            slots = [None]*_NUM_SLOTS
        for i in range(_NUM_SLOTS):
            self.save_buttons[i].setText(self.t('save'))
            self.jump_buttons[i].setText(self.t('go'))
            self.slot_checks[i].setToolTip(self.t('selected_tip'))
            defaults = {_tr('view', language=lang, n=i+1) for lang in _TRANSLATIONS}
            if not isinstance(slots[i],dict) and self.edits[i].text() in defaults:
                self.edits[i].setText(self.t('view',n=i+1))
        self.capture_group.setTitle(self.t('capture_short'))
        self.region_button.setText(self.t('select_short'))
        self.region_button.setToolTip(self.t('tooltip_area'))
        self.outline_check.setText(self.t('outline_short'))
        self.outline_check.setToolTip(self.t('tooltip_outline'))
        self.capture_button.setText(_lang_text(self._lang, '이미지 촬영', 'Capture image'))
        self.capture_button.setToolTip(self.t('tooltip_capture'))
        mode_labels=_MODE_TRANSLATIONS.get(self._lang,_MODE_TRANSLATIONS['en'])
        for idx,label in enumerate(mode_labels):
            self.global_mode_combo.setItemText(idx,label)
            self.single_slot_mode.setItemText(idx+1,label)
        inherit_label=_INHERIT_TRANSLATIONS.get(self._lang,_INHERIT_TRANSLATIONS['en'])
        self.single_slot_mode.setItemText(0,inherit_label)
        self.global_mode_label.setText(_lang_text(self._lang, '표시', 'Display'))
        self.global_mode_combo.setToolTip(_lang_text(self._lang, '실험 기능: Painter API에서 직접 채널 선택을 지원하지 않아 자동 전환은 환경에 따라 실패할 수 있습니다.', 'Experimental: Painter Python API has no stable channel setter, so automatic switching may fail.'))
        self.batch_button.setText(self.t('batch_short'))
        self.batch_button.setToolTip(self.t('tooltip_batch'))
        self.output_group.setTitle(self.t('output_short'))
        self.file_name_label.setText(self.t('filename_short'))
        self.file_name_edit.setToolTip(self.t('tooltip_name'))
        self.format_label.setText(_lang_text(self._lang, '형식', 'Format'))
        self.format_combo.setToolTip(_lang_text(self._lang, '스크린샷 저장 형식입니다.', 'Image file format for captures.'))
        self.browse_button.setText(self.t('change_short'))
        self.browse_button.setToolTip(self.t('tooltip_folder'))
        self.open_after_check.setText(self.t('open_short'))
        self.preview_mode.setItemText(0,self.t('gallery_short'))
        self.preview_mode.setItemText(1,self.t('single_short'))
        self.preview_mode.setToolTip(self.t('preview_mode_tip'))
        self.layout_group.setTitle(self.t('layout_short'))
        self.layout_label.setText(self.t('layout_short'))
        self.layout_combo.setItemText(0,self.t('layout_row'))
        self.layout_combo.setItemText(1,self.t('layout_three'))
        self.layout_combo.setItemText(2,self.t('layout_two'))
        self.gap_label.setText(self.t('gap_short'))
        self.delay_label.setText(self.t('delay_short'))
        self.delay_spin.setToolTip(self.t('tooltip_delay'))
        self.crop_check.setText(self.t('crop_short'))
        self.crop_check.setToolTip(self.t('tooltip_crop'))
        self.export_group.setTitle(self.t('export_group'))
        self.export_button.setText(self.t('export_short'))
        self.export_button.setToolTip(self.t('export_tip'))
        self.import_button.setText(self.t('import_short'))
        self.import_button.setToolTip(self.t('import_tip'))
        self.refresh_button.setText(self.t('refresh'))
        self.refresh_button.setToolTip(self.t('tooltip_refresh'))
        self.single_options.setTitle(_lang_text(self._lang, '선택된 뷰 옵션', 'Selected view options'))
        self.single_slot_mode_label.setText(_lang_text(self._lang, '표시', 'Display'))
        self._update_capture_labels()

    def _on_pin_toggled(self, checked):
        checked = bool(checked)
        if checked != self.pinned_mode and not self._capture_busy:
            self.status.setText(self.t('switching'))
            _schedule_switch_mode(checked)

    def _on_outline_toggled(self, checked):
        _settings().setValue('region_outline_v13','true' if checked else 'false')
        try:
            _update_global_outline()
        except Exception as e:
            self._error(e)

    def _set_slot_count(self, n):
        count = _safe_int(n,6,1,10)
        for i,widget in enumerate(self.slot_rows):
            widget.setVisible(i<count)
        for i,widget in enumerate(self.gallery_frames):
            widget.setVisible(i<count)
        self.slot_scroll.setFixedHeight(min(275, max(38,34*count+8)))
        _settings().setValue('visible_slots',count)
        if hasattr(self, "single_combo"):
            self._refresh_single_preview()

    def _toggle_slot_selection(self,i,checked):
        if not project.is_open():
            return
        try:
            vals = _get_selection()
            vals[i] = bool(checked)
            _set_selection(vals)
        except Exception as e:
            self._error(e)

    def _select_all_slots(self, checked):
        if not project.is_open() or self._capture_busy:
            return
        vals = _get_selection()
        for i in range(self.slot_count_spin.value()):
            vals[i] = bool(checked)
            self.slot_checks[i].blockSignals(True)
            self.slot_checks[i].setChecked(bool(checked))
            self.slot_checks[i].blockSignals(False)
        _set_selection(vals)

    def _get_image_from_slot(self,slot):
        encoded = slot.get('thumbnail_jpeg_v12') if isinstance(slot,dict) else None
        if encoded:
            try:
                pm = QtGui.QPixmap()
                if pm.loadFromData(base64.b64decode(encoded)):
                    return pm
            except Exception as e:
                print('[ViewAtlas] Thumbnail decode error:',repr(e))
        return None

    def _refresh_previews(self):
        try:
            slots = _get_slots() if project.is_open() else [None]*_NUM_SLOTS
        except Exception:
            slots = [None]*_NUM_SLOTS
        for i, entry in enumerate(slots):
            label = self.preview_images[i]
            pm = self._get_image_from_slot(entry)
            if pm is not None:
                label.setText('')
                label.setPixmap(pm.scaled(label.width()-6,label.height()-6,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation))
            else:
                label.setPixmap(QtGui.QPixmap())
                label.setText('—')
            name = entry.get('name',self.t('view',n=i+1)) if isinstance(entry,dict) else self.t('view',n=i+1)
            self.gallery_names[i].setText(f'{i+1}. {name}')
            self.gallery_names[i].setToolTip(name)
            self.single_combo.setItemText(i,f'{i+1}. {name}')
        self._refresh_single_preview()

    def _refresh_single_preview(self, *args):
        if not hasattr(self,'single_combo') or not hasattr(self,'single_image'):
            return
        i = self.single_combo.currentIndex()
        if i < 0:
            return
        if project.is_open():
            try: entry = _get_slots()[i]
            except Exception: entry = None
        else:
            entry = None
        pm = self._get_image_from_slot(entry)
        if pm is not None:
            self.single_image.setText('')
            self.single_image.setPixmap(pm.scaled(335,285,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation))
        else:
            self.single_image.setPixmap(QtGui.QPixmap())
            self.single_image.setText(self.t('no_thumb'))
        self.single_meta.setText(self.single_combo.currentText())
        self._load_selected_slot_options()

    def _change_preview_mode(self,index):
        self.preview_stack.setCurrentIndex(index)
        _settings().setValue('preview_mode_v13',index)
        self._refresh_single_preview()

    def _current_single_slot_index(self):
        return max(0, min(_NUM_SLOTS-1, self.single_combo.currentIndex()))

    def _load_selected_slot_options(self):
        try:
            slot = _get_slots()[self._current_single_slot_index()] if project.is_open() else None
        except Exception:
            slot = None
        mode = _slot_capture_mode(slot)
        self.single_slot_mode.blockSignals(True)
        self.single_slot_mode.setCurrentIndex(max(0, self.single_slot_mode.findData(mode)))
        self.single_slot_mode.blockSignals(False)

    def _save_selected_slot_options(self, *args):
        if not project.is_open():
            return
        i = self._current_single_slot_index()
        slots = _get_slots()
        if not isinstance(slots[i], dict):
            return
        slots[i]['capture_mode_v14'] = self.single_slot_mode.currentData()
        _metadata().set(_KEY, slots)

    def _step_single(self,delta):
        length = self.slot_count_spin.value()
        self.single_combo.setCurrentIndex((self.single_combo.currentIndex()+delta)%length)

    def _capture_thumbnail_for_slot(self,i,camera_state):
        rect = _get_region()
        if rect is None or self._capture_busy:
            self.status.setText(self.t('thumbnail_need_region'))
            return
        self._capture_busy = True
        self._thumb_pending = (i,camera_state)
        self._update_capture_labels()
        self.status.setText(self.t('thumbnail_pending'))
        _hide_host()
        _hide_outline()
        try:
            ui.get_main_window().raise_()
        except Exception:
            pass
        QtCore.QTimer.singleShot(500,lambda: self._complete_thumbnail(i,camera_state,rect))

    def _complete_thumbnail(self,i,camera_state,rect):
        if not _qt_object_alive(self):
            return
        try:
            if self._thumb_pending != (i,camera_state):
                return
            captured = _grab_viewport(rect)
            pm = QtGui.QPixmap.fromImage(captured)
            encoded = _thumbnail_from_pixmap(pm)
            if not encoded:
                raise RuntimeError('Thumbnail encode failed')
            slots = _get_slots()
            entry = slots[i]
            if isinstance(entry,dict) and entry.get('camera') == camera_state:
                entry['thumbnail_jpeg_v12'] = encoded
                slots[i] = entry
                _metadata().set(_KEY,slots)
                self._refresh_previews()
                self.status.setText(self.t('thumbnail_done',name=entry.get('name',str(i+1))))
        except Exception as e:
            self._error(e)
        finally:
            self._thumb_pending = None
            self._capture_busy = False
            self._update_capture_labels()
            _show_host()
            _restore_outline()

    def _error(self,exception):
        self.status.setText(self.t('error',error=exception))
        self.status.setToolTip(str(exception))
        print('[ViewAtlas]',repr(exception))
        traceback.print_exc()

    def refresh(self):
        try:
            if not project.is_open():
                for i in range(_NUM_SLOTS):
                    self.jump_buttons[i].setEnabled(False)
                    self.slot_checks[i].setEnabled(False)
                self._refresh_previews()
                self.status.setText(self.t('project_needed'))
                return
            slots = _get_slots()
            checks = _get_selection()
            for i,item in enumerate(slots):
                self.edits[i].setText(item.get('name',self.t('view',n=i+1)) if isinstance(item,dict) else self.t('view',n=i+1))
                valid = isinstance(item,dict) and isinstance(item.get('camera'),dict)
                self.jump_buttons[i].setEnabled(valid)
                self.slot_checks[i].blockSignals(True)
                self.slot_checks[i].setChecked(checks[i])
                self.slot_checks[i].setEnabled(valid)
                self.slot_checks[i].blockSignals(False)
            self._refresh_previews()
            self.status.setText(self.t('status_ready'))
        except Exception as e:
            self._error(e)
        self._update_capture_labels()

    def save_slot(self,i):
        try:
            if self._capture_busy: return
            state = _capture()
            slots = _get_slots()
            name = self.edits[i].text().strip() or self.t('view',n=i+1)
            previous = slots[i] if isinstance(slots[i], dict) else {}
            slots[i] = {'name':name,'camera':state,'capture_mode_v14':previous.get('capture_mode_v14','inherit')}
            _metadata().set(_KEY,slots)
            self.jump_buttons[i].setEnabled(True)
            self.slot_checks[i].setEnabled(True)
            self._refresh_previews()
            self.status.setText(self.t('saved',name=name))
            self._capture_thumbnail_for_slot(i,state)
        except Exception as e:
            self._error(e)

    def restore_slot(self,i):
        try:
            item = _get_slots()[i]
            if not isinstance(item,dict) or 'camera' not in item:
                self.status.setText(self.t('empty'))
                return
            _restore(item['camera'])
            self.status.setText(self.t('moved',name=item.get('name',self.t('view',n=i+1))))
        except Exception as e:
            self._error(e)

    def rename_slot(self,i):
        try:
            if not project.is_open():return
            slots = _get_slots()
            if not isinstance(slots[i],dict):return
            slots[i]['name'] = self.edits[i].text().strip() or self.t('view',n=i+1)
            _metadata().set(_KEY,slots)
            self._refresh_previews()
        except Exception as e:
            self._error(e)

    def _update_capture_labels(self):
        rect = _get_region()
        self.region_label.setText(f'{rect.width()} × {rect.height()} px' if rect else self.t('no_area'))
        path = QtCore.QDir.toNativeSeparators(_output_dir())
        # Simple elision for long local paths, with full tooltip & selectable text.
        self.folder_label.setText('…'+path[-43:] if len(path)>46 else path)
        self.folder_label.setToolTip(path)
        for control in (self.region_button,self.outline_check):
            control.setEnabled(not self._capture_busy)
        self.capture_button.setEnabled(rect is not None and not self._capture_busy)
        self.batch_button.setEnabled(rect is not None and not self._capture_busy and project.is_open())
        for b in self.save_buttons:
            b.setEnabled(not self._capture_busy)
        if hasattr(self,'export_button'):
            self.export_button.setEnabled(project.is_open() and not self._capture_busy)
            self.import_button.setEnabled(project.is_open() and not self._capture_busy)

    def choose_folder(self):
        try:
            directory = QtWidgets.QFileDialog.getExistingDirectory(self,self.t('choose_folder'),_output_dir())
            if directory:
                _settings().setValue('output_dir',directory)
                self._update_capture_labels()
        except Exception as e:
            self._error(e)

    def _global_capture_mode(self):
        return self.global_mode_combo.currentData() or 'current'

    def _capture_view_sequence(self, rect, mode, on_finish):
        """Capture one channel / Material. Async repaint and no stored host widget."""
        self._capture_generation = getattr(self, '_capture_generation', 0) + 1
        generation = self._capture_generation
        display_before = _display_state_snapshot() if mode != 'current' else None
        done = [False]

        def alive():
            return (_qt_object_alive(self) and
                    self._capture_generation == generation and self._capture_busy)

        def finish(image=None, error=None):
            if done[0]:
                return
            done[0] = True
            if mode != 'current':
                try:
                    _restore_display_snapshot(display_before)
                except Exception as exc:
                    print('[ViewAtlas] Display restore:', repr(exc))
            if alive():
                on_finish(image, error)

        def take_shot():
            if not alive():
                return
            try:
                finish(_grab_viewport(rect), None)
            except Exception as exc:
                finish(None, exc)

        try:
            if mode != 'current':
                _set_viewport_mode_experimental(mode)
            QtCore.QTimer.singleShot(350 if mode != 'current' else 90, take_shot)
        except Exception as exc:
            finish(None, exc)

    def select_region(self):
        global _selector
        if self._selector_pending or self._capture_busy:
            return
        self._selector_pending = True
        self.status.setText(self.t('select_instruction'))
        _hide_host()
        _hide_outline()
        QtCore.QTimer.singleShot(180,self._start_region_selector)

    def _start_region_selector(self):
        global _selector
        try:
            main = ui.get_main_window()
            main.raise_()
            main.activateWindow()
            _selector = ViewportRegionSelector(main,self._region_selected)
            _selector.show()
            _selector.raise_()
            _selector.activateWindow()
            _selector.setFocus()
        except Exception as e:
            self._selector_pending = False
            _show_host()
            _restore_outline()
            self._error(e)

    def _region_selected(self,rect):
        global _selector
        _selector = None
        self._selector_pending = False
        if rect is not None:
            _set_region(rect)
            self.status.setText(self.t('select_success',w=rect.width(),h=rect.height()))
        else:
            self.status.setText(self.t('select_cancel'))
        self._update_capture_labels()
        _show_host()
        _restore_outline()

    def _open_saved_image(self,path):
        if path and os.path.isfile(path):
            try:
                if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)):
                    self.status.setText(self.t('open_failed',path=path))
            except Exception as e:
                print('[ViewAtlas] Viewer:',repr(e))

    def save_screenshot(self):
        if self._capture_busy: return
        rect = _get_region()
        if rect is None:
            self.status.setText(self.t('need_region'))
            return
        folder = _output_dir()
        if not os.path.isdir(folder):
            self.status.setText(self.t('bad_dir'))
            return
        self._capture_busy = True
        self._update_capture_labels()
        self.status.setText(self.t('taking'))
        _hide_host()
        _hide_outline()
        try: ui.get_main_window().raise_()
        except Exception: pass
        filename = self.file_name_edit.text()
        open_after = self.open_after_check.isChecked()
        fmt = self.format_combo.currentData()
        mode = self._global_capture_mode()
        QtCore.QTimer.singleShot(450,lambda:self._do_screenshot(rect,folder,filename,open_after,fmt,mode))

    def _do_screenshot(self,rect,folder,filename,open_after,fmt,mode):
        def received(img,error):
            path=None
            try:
                if error is not None:
                    raise error
                path=_new_output_path(folder,filename,'single',fmt)
                if not _save_image_to_path(img,path,fmt):
                    raise RuntimeError('Image save failed: '+path)
                self.status.setText(self.t('saved_png',path=path))
                self.status.setToolTip(path)
            except Exception as exc:
                path=None
                self._error(exc)
            finally:
                self._capture_busy=False
                self._update_capture_labels()
                _show_host()
                _restore_outline()
                if path and open_after:
                    QtCore.QTimer.singleShot(150,lambda p=path:self._open_saved_image(p))
        try:
            self._capture_view_sequence(rect,mode,received)
        except Exception as exc:
            received(None,exc)

    def save_batch_screenshot(self):
        if self._capture_busy:return
        try:
            rect = _get_region()
            if rect is None: raise RuntimeError(self.t('need_region'))
            if not project.is_open():raise RuntimeError(self.t('project_needed'))
            folder = _output_dir()
            if not os.path.isdir(folder):raise RuntimeError(self.t('bad_dir'))
            saved = [(i+1,s.get('name',self.t('view',n=i+1)),s)
                for i,s in enumerate(_get_slots()[:self.slot_count_spin.value()])
                if isinstance(s,dict) and isinstance(s.get('camera'),dict) and self.slot_checks[i].isChecked()]
            if not saved: raise RuntimeError(self.t('no_selection'))
            self._batch_state = dict(views=saved,index=0,images=[],rect=rect,folder=folder,
                filename=self.file_name_edit.text(),open_after=self.open_after_check.isChecked(),
                original=_capture(), out_format=self.format_combo.currentData(), columns=[len(saved),3,2][self.layout_combo.currentIndex()],
                gap=self.gap_spin.value(),crop=self.crop_check.isChecked(),
                delay=self.delay_spin.value())
            self._capture_busy = True
            self._update_capture_labels()
            self.status.setText(self.t('batch_progress',count=len(saved)))
            _hide_host()
            _hide_outline()
            try: ui.get_main_window().raise_()
            except Exception: pass
            QtCore.QTimer.singleShot(200,self._batch_move_next)
        except Exception as e:
            self._error(e)

    def _batch_move_next(self):
        state = self._batch_state
        if state is None:return
        try:
            i = state['index']
            if i>=len(state['views']):
                self._finish_batch()
                return
            slot_num,name,slot = state['views'][i]
            _restore(slot['camera'])
            QtCore.QTimer.singleShot(state['delay'],self._batch_capture_current)
        except Exception as e:
            self._finish_batch(e)

    def _batch_capture_current(self):
        state=self._batch_state
        if state is None:
            return
        try:
            _num,_name,slot=state['views'][state['index']]
            mode=_slot_capture_mode(slot)
            if mode == 'inherit':
                mode = self._global_capture_mode()
            def received(image,error):
                if self._batch_state is not state:
                    return
                try:
                    if error is not None:
                        raise error
                    if state['crop']:
                        w=min(image.width(),max(1,image.height()//2))
                        image=image.copy((image.width()-w)//2,0,w,image.height())
                        image.setDevicePixelRatio(1.0)
                    state['images'].append(image)
                    state['index']+=1
                    QtCore.QTimer.singleShot(120,self._batch_move_next)
                except Exception as exc:
                    self._finish_batch(exc)
            self._capture_view_sequence(state['rect'],mode,received)
        except Exception as exc:
            self._finish_batch(exc)

    def _finish_batch(self,error=None):
        state = self._batch_state
        if state is None:return
        self._batch_state = None
        path = None
        try:
            if error is None:
                path = self._write_contact_sheet(state)
        except Exception as e:
            error = e
        finally:
            try: _restore(state['original'])
            except Exception as e:
                print('[ViewAtlas] Original camera restore failed:',repr(e))
                if error is None:error=e
            self._capture_busy = False
            self._update_capture_labels()
            _show_host()
            _restore_outline()
        if error is not None:
            self._error(error)
        else:
            self.status.setText(self.t('batch_success',count=len(state['images']),path=path))
            self.status.setToolTip(path)
            if state['open_after']:
                QtCore.QTimer.singleShot(150,lambda p=path:self._open_saved_image(p))

    def _write_contact_sheet(self,state):
        images = state['images']
        if not images:raise RuntimeError(self.t('no_images'))
        cols = min(state['columns'],len(images))
        rows = (len(images)+cols-1)//cols
        gap = state['gap']
        width = max(img.width() for img in images)
        height = max(img.height() for img in images)
        out_w = cols*width+(cols-1)*gap
        out_h = rows*height+(rows-1)*gap
        if out_w*out_h > 120_000_000:
            raise RuntimeError(f'{out_w}×{out_h}: '+self.t('image_too_large'))
        result = QtGui.QImage(out_w,out_h,QtGui.QImage.Format_RGB32)
        if result.isNull():raise RuntimeError(self.t('out_of_memory'))
        result.setDevicePixelRatio(1.0)
        result.fill(QtGui.QColor('#101010'))
        painter = QtGui.QPainter(result)
        try:
            for i,img in enumerate(images):
                x = (i%cols)*(width+gap)+(width-img.width())//2
                y = (i//cols)*(height+gap)+(height-img.height())//2
                painter.drawImage(QtCore.QRect(x,y,img.width(),img.height()),img)
        finally:
            painter.end()
        path = _new_output_path(state['folder'],state['filename'],'all', state.get('out_format','png'))
        if not _save_image_to_path(result, path, state.get('out_format','png')):
            raise RuntimeError(self.t('png_fail',path=path))
        return path

    def export_json(self):
        try:
            if not project.is_open():raise RuntimeError(self.t('no_project'))
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(self,self.t('export_short'),
                os.path.join(_output_dir(),'ViewAtlas_Preset.json'),'JSON (*.json)')
            if not filename:return
            if not filename.lower().endswith('.json'): filename += '.json'
            rect = _get_region()
            opts = dict(visible_slots=self.slot_count_spin.value(),collage_layout=self.layout_combo.currentIndex(),
                collage_gap=self.gap_spin.value(),collage_delay_ms=self.delay_spin.value(),
                center_crop=self.crop_check.isChecked(),
                output_format=self.format_combo.currentData(),global_capture_mode=self._global_capture_mode(),
                capture_rect=[rect.x(),rect.y(),rect.width(),rect.height()] if rect else None)
            clean_slots = [({k: v for k, v in slot.items() if k != 'split_mode_v14'}
                            if isinstance(slot, dict) else None) for slot in _get_slots()]
            data = dict(format='ViewAtlas',schema=1,created=datetime.now().isoformat(timespec='seconds'),
                        slots=clean_slots,selected=_get_selection(),settings=opts)
            with open(filename,'w',encoding='utf-8') as f:
                json.dump(data,f,ensure_ascii=False,indent=2)
            self.status.setText(self.t('file_exported',path=filename))
            self.status.setToolTip(filename)
        except Exception as e:
            self._error(e)

    def import_json(self):
        try:
            if not project.is_open():raise RuntimeError(self.t('no_project'))
            filename,_ = QtWidgets.QFileDialog.getOpenFileName(self,self.t('import_short'),
                          _output_dir(),'JSON (*.json)')
            if not filename:return
            if os.path.getsize(filename)>12_000_000:raise ValueError('File exceeds 12 MB')
            with open(filename,'r',encoding='utf-8') as f:
                data = json.load(f)
            slots,selection,opts,region = _validate_import(data)
            answer = QtWidgets.QMessageBox.question(self,APP_NAME,self.t('replace_confirm'),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:return
            _metadata().set(_KEY,slots)
            _set_selection(selection)
            self.slot_count_spin.setValue(opts['visible_slots'])
            self.layout_combo.setCurrentIndex(opts['collage_layout'])
            self.gap_spin.setValue(opts['collage_gap'])
            self.delay_spin.setValue(opts['collage_delay_ms'])
            self.crop_check.setChecked(opts['center_crop'])
            self.format_combo.setCurrentIndex(max(0,self.format_combo.findData(opts.get('output_format','png'))))
            self.global_mode_combo.setCurrentIndex(max(0,self.global_mode_combo.findData(opts.get('global_capture_mode','current'))))
            warning = ''
            if region is not None:
                screen = QtGui.QGuiApplication.screenAt(region.center())
                if screen is not None and screen.geometry().contains(region):
                    _set_region(region)
                else:
                    warning = self.t('region_mismatch')
            self.refresh()
            _update_global_outline()
            self._update_capture_labels()
            self.status.setText(self.t('file_imported')+(' '+warning if warning else ''))
        except Exception as e:
            self._error(e)

    def cancel_batch(self):
        self._capture_generation = getattr(self, '_capture_generation', 0) + 1
        state = self._batch_state
        self._batch_state = None
        if state is not None:
            try:_restore(state['original'])
            except Exception:pass
        self._thumb_pending = None
        self._capture_busy = False



def show_bookmarks(pinned=None):
    global _widget, _dock, _standalone
    if pinned is None:
        pinned = _is_pinned_mode()
    pinned = bool(pinned)
    frame = ui.get_main_window().frameGeometry()
    width = 425
    height = max(480,min(720,frame.height()-90))
    if pinned:
        _destroy_dock()
        if _standalone is None:
            _standalone = CameraBookmarksPanel(True)
            _standalone.setWindowFlags(QtCore.Qt.Window |
                                       QtCore.Qt.WindowStaysOnTopHint)
        _standalone.resize(width,height)
        _standalone.move(frame.right()-width-15,frame.top()+25)
        _standalone.show()
        _standalone.raise_()
        _standalone.activateWindow()
        _standalone.refresh()
        _standalone._update_capture_labels()
    else:
        _destroy_standalone()
        if _dock is None:
            _widget = CameraBookmarksPanel(False)
            _dock = ui.add_dock_widget(_widget)
        _dock.setFloating(True)
        _dock.setWindowIcon(_brand_icon())
        _dock.resize(width,height)
        _dock.move(frame.center().x()-width//2,frame.center().y()-height//2)
        _dock.show()
        _dock.raise_()
        _dock.activateWindow()
        _widget.refresh()
        _widget._update_capture_labels()
    try:
        _update_global_outline()
    except Exception as e:
        print('[ViewAtlas] Outline error:',repr(e))
    print('[ViewAtlas] V15.0 panel displayed')


def start_plugin():
    global _action
    try:
        _ensure_app_state_signal()
        if _action is None:
            _action = _ACTION_CLASS(APP_NAME,ui.get_main_window())
            _action.setIcon(_brand_icon())
            _action.triggered.connect(lambda:show_bookmarks(_is_pinned_mode()))
            ui.add_action(ui.ApplicationMenu.Window,_action)
        show_bookmarks(_is_pinned_mode())
    except Exception as e:
        print('[ViewAtlas] START ERROR:',repr(e))
        traceback.print_exc()
        raise


def close_plugin():
    global _selector, _action, _region_preview
    if _region_preview is not None:
        _region_preview.hide()
        _region_preview.deleteLater()
        _region_preview = None
    if _selector is not None:
        _selector.close()
        _selector = None
    if _action is not None:
        ui.delete_ui_element(_action)
        _action = None
    _destroy_dock()
    _destroy_standalone()


if __name__ == '__main__':
    start_plugin()