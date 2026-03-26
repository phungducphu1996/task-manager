<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

const AUTH_STORAGE_KEY = 'social_shared_auth'
const TIMELINE_PREFS_KEY = 'social_timeline_prefs_v1'
const DEFAULT_NOTE_COLOR = '#f2f0e2'
const DEFAULT_CAMPAIGN_COLOR = '#d8d2bc'
const DEFAULT_CAMPAIGN_ICON = '📌'
const QUICK_NOTE_MAX_LENGTH = 256
const COMMENT_MEDIA_PREFIX = '[media]'
const NOTE_COLOR_PRESETS = ['#f2f0e2', '#f4e2ef', '#e6ecf9', '#fde7d7', '#dff5e8', '#fff3c8', '#e8e4fb', '#f8f8f8']
const CAMPAIGN_COLOR_PRESETS = ['#3f5bd8', '#6a38c2', '#cb4295', '#ea6230', '#e59638', '#d9b743', '#59b058', '#59b6b8']
const CAMPAIGN_ICON_PRESETS = ['📌', '🏃', '⭐', '💡', '📅', '🎁', '🎄', '🍎', '🎉', '🎯', '⚡', '❤️', '🏆', '🚀']
const statusOrder = ['idea', 'design', 'ready', 'posted']
const statusLabels = {
  idea: 'Idea',
  design: 'Design',
  ready: 'Ready',
  posted: 'Posted'
}

const kanban = ref({ idea: [], design: [], ready: [], posted: [] })
const calendarTasks = ref([])
const analytics = ref({ total_this_week: 0, overdue_count: 0, campaign_count: 0 })
const users = ref([])
const campaigns = ref([])
const loading = ref(false)
const authLoading = ref(false)
const activeView = ref('overview')
const settingsOpen = ref(false)

const auth = reactive({
  token: '',
  user: null,
  username: '',
  password: ''
})

const visibleFields = reactive({
  type: true,
  airDate: true,
  assignee: true
})

const detailOpen = ref(false)
const selectedTask = ref(null)
const selectedTaskId = ref(null)
const activeTab = ref('content')
const createMode = ref(false)
const createType = ref('story')
const assigneePickerOpen = ref(false)
const assigneePickerRef = ref(null)

const draggingTaskId = ref(null)
const dragOverStatus = ref('')
const detailPendingMedia = ref([])
const commentPendingMedia = ref([])
const failedTimelineThumbs = ref(new Set())
const timelineViewportRef = ref(null)
const timelinePrefs = reactive({
  dayWidth: 220,
  cardScale: 120
})
const timelinePanState = reactive({
  active: false,
  startX: 0,
  startScrollLeft: 0
})
const timelineAutoFocusDone = ref(false)
const notePreview = reactive({
  open: false,
  taskId: '',
  title: '',
  note: '',
  color: DEFAULT_NOTE_COLOR,
  savedColor: DEFAULT_NOTE_COLOR,
  draft: '',
  airDate: null,
  source: '',
  saving: false
})
const previewDevice = ref('mobile')
const previewCarouselIndex = ref(0)
const previewLinkState = reactive({
  loading: false,
  generating: false,
  data: null
})

const toast = reactive({
  show: false,
  message: '',
  error: false,
  timer: null
})

const contentForm = reactive({
  title: '',
  quick_note: '',
  note_color: DEFAULT_NOTE_COLOR,
  caption: '',
  hashtags: '',
  mentions: '',
  assignee_name: '',
  campaign_name: '',
  air_date: ''
})

const checklistText = ref('')
const commentText = ref('')
const statusValue = ref('idea')

const campaignStatusOptions = ['planning', 'active', 'completed', 'paused']
const campaignEditor = reactive({
  open: false,
  saving: false,
  editingId: '',
  name: '',
  status: 'planning',
  start_date: '',
  end_date: '',
  link_url: '',
  description: '',
  color: DEFAULT_CAMPAIGN_COLOR,
  icon: DEFAULT_CAMPAIGN_ICON,
  requires_product_url: false,
  brand: '',
  platform: ''
})

const profileForm = reactive({
  name: '',
  username: '',
  avatar_url: '',
  zalo_user_id: ''
})

const passwordForm = reactive({
  current_password: '',
  new_password: '',
  confirm_password: ''
})

const profileSaving = ref(false)
const passwordSaving = ref(false)

const userEditor = reactive({
  name: '',
  username: '',
  role: 'content',
  zalo_user_id: '',
  password: ''
})
const usersLoading = ref(false)
const userRows = ref([])
const profileAvatarFile = ref(null)
const newUserAvatarFile = ref(null)
const rowAvatarFiles = reactive({})
const zaloSettingsSaving = ref(false)
const zaloTestSending = ref(false)
const zaloSettingsForm = reactive({
  social_group_chat_id: '',
  source: 'none'
})

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function parseSpaceList(raw) {
  return String(raw || '')
    .split(/\s+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseLineList(raw) {
  return String(raw || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseChecklistLines(raw) {
  return parseLineList(raw).map((line, index) => {
    const match = line.match(/^\[(x|X| )\]\s*(.+)$/)
    if (match) {
      return {
        title: match[2].trim(),
        is_done: match[1].toLowerCase() === 'x',
        position: index
      }
    }
    return { title: line, is_done: false, position: index }
  })
}

function fmtDate(value, withTime = true) {
  if (!value) return 'No air date'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return 'Invalid date'
  const options = withTime
    ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { month: 'short', day: 'numeric', year: 'numeric' }
  return new Intl.DateTimeFormat('en-US', options).format(date)
}

function nameKey(value) {
  return String(value || '').trim().toLowerCase()
}

function findUserByAssignee(value) {
  const key = nameKey(value)
  if (!key) return null
  return users.value.find((user) => {
    const nameMatch = nameKey(user.name) === key
    const usernameMatch = nameKey(user.username) === key
    return nameMatch || usernameMatch
  }) || null
}

function assigneeAvatarUrl(value) {
  return findUserByAssignee(value)?.avatar_url || ''
}

function assigneeInitials(value) {
  const clean = String(value || '').trim()
  if (!clean) return 'U'
  const words = clean.split(/\s+/).filter(Boolean)
  if (words.length === 1) return words[0].slice(0, 1).toUpperCase()
  return `${words[0][0] || ''}${words[1][0] || ''}`.toUpperCase()
}

function assigneeAvatarColor(value) {
  const palette = ['#e1582f', '#2d9fbc', '#6351c6', '#17a964', '#e4a327', '#d35a83']
  const key = nameKey(value)
  if (!key) return '#7e7a6f'
  let hash = 0
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) % 2147483647
  }
  return palette[Math.abs(hash) % palette.length]
}

function assigneeDisplay(value) {
  return String(value || '').trim() || 'Unassigned'
}

function assetFileName(url) {
  const raw = String(url || '').trim()
  if (!raw) return 'media-file'
  try {
    const pathname = new URL(raw, window.location.origin).pathname || ''
    const base = pathname.split('/').pop() || raw
    return decodeURIComponent(base) || 'media-file'
  } catch {
    const base = raw.split('/').pop() || raw
    return base || 'media-file'
  }
}

function commentAuthorName(comment) {
  const userId = String(comment?.user_id || '').trim()
  if (userId) {
    const found = users.value.find((user) => String(user?.id || '') === userId)
    if (found) {
      return String(found.name || found.username || 'User')
    }
    return `User ${userId.slice(0, 6)}`
  }
  return 'User'
}

function commentAuthorAvatar(comment) {
  const userId = String(comment?.user_id || '').trim()
  if (!userId) return ''
  const found = users.value.find((user) => String(user?.id || '') === userId)
  return found?.avatar_url || ''
}

function fmtTime(value) {
  if (!value) return '--:--'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return '--:--'
  return new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

function onlyDateKey(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return ''
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

function toInputDatetime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return ''
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day}T${hour}:${minute}`
}

function parseIsoDay(value) {
  const raw = String(value || '').trim()
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return null
  const y = Number(match[1])
  const m = Number(match[2]) - 1
  const d = Number(match[3])
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return null
  const date = new Date(y, m, d)
  if (Number.isNaN(date.valueOf())) return null
  return date
}

function campaignTimelineIcon(status) {
  const key = String(status || '').toLowerCase()
  if (key === 'active') return '🟢'
  if (key === 'completed') return '✅'
  if (key === 'paused') return '⏸️'
  return '📅'
}

function initials(name) {
  return (name || 'NA')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || '')
    .join('') || 'NA'
}

function isLikelyImage(url) {
  if (!url) return false
  if (isDemoAssetUrl(url)) return false
  return !/\.(mp4|mov|m4v|avi|mkv|webm)(\?.*)?$/i.test(url)
}

function isLikelyMediaUrl(url) {
  const raw = String(url || '').trim()
  if (!raw) return false
  if (raw.startsWith('/media/')) return true
  return /^(https?:\/\/\S+|\/\S+)\.(jpg|jpeg|png|webp|gif|mp4|mov|m4v|avi|mkv|webm)(\?.*)?$/i.test(raw)
}

function isDemoAssetUrl(url) {
  return /cdn\.example\.com/i.test(String(url || ''))
}

function isTimelineThumbVisible(url) {
  if (!url) return false
  return isLikelyImage(url) && !failedTimelineThumbs.value.has(url)
}

function markTimelineThumbFailed(url) {
  if (!url) return
  const next = new Set(failedTimelineThumbs.value)
  next.add(url)
  failedTimelineThumbs.value = next
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function sanitizeHexColor(value, fallback = DEFAULT_NOTE_COLOR) {
  const raw = String(value || '').trim()
  return /^#[0-9a-fA-F]{6}$/.test(raw) ? raw.toLowerCase() : fallback
}

function sanitizeCampaignColor(value, fallback = DEFAULT_CAMPAIGN_COLOR) {
  return sanitizeHexColor(value, fallback)
}

function normalizeCampaignIcon(value, fallback = DEFAULT_CAMPAIGN_ICON) {
  const clean = String(value || '').trim()
  return clean || fallback
}

function normalizeQuickNote(value) {
  const raw = String(value ?? '')
  if (!raw.trim()) return ''
  return raw.trim().slice(0, QUICK_NOTE_MAX_LENGTH)
}

function taskNoteColor(task) {
  return sanitizeHexColor(task?.note_color, DEFAULT_NOTE_COLOR)
}

function noteCardStyle(task) {
  return { '--note-bg': taskNoteColor(task) }
}

function setContentNoteColor(value) {
  contentForm.note_color = sanitizeHexColor(value, DEFAULT_NOTE_COLOR)
}

function setNotePreviewColor(value) {
  notePreview.color = sanitizeHexColor(value, DEFAULT_NOTE_COLOR)
}

function parseCommentContent(raw) {
  const lines = String(raw || '').split('\n')
  const textLines = []
  const media = []
  lines.forEach((line) => {
    const trimmed = String(line || '').trim()
    if (!trimmed) {
      textLines.push('')
      return
    }
    if (trimmed.startsWith(COMMENT_MEDIA_PREFIX)) {
      const url = trimmed.slice(COMMENT_MEDIA_PREFIX.length).trim()
      if (url) media.push(url)
      return
    }
    if (isLikelyMediaUrl(trimmed)) {
      media.push(trimmed)
      return
    }
    textLines.push(line)
  })
  return {
    text: textLines.join('\n').trim(),
    media,
  }
}

function commentDisplayText(comment) {
  const parsed = parseCommentContent(comment?.content)
  if (parsed.text) return parsed.text
  if (parsed.media.length > 0) return 'Attached media'
  return ''
}

function commentMediaUrls(comment) {
  return parseCommentContent(comment?.content).media
}

function previewCaptionText() {
  const raw = String(contentForm.caption || selectedTask.value?.caption || '').trim()
  return raw
}

function previewHashtagText() {
  const parsed = parseSpaceList(contentForm.hashtags || (selectedTask.value?.hashtags || []).join(' '))
  return parsed.join(' ')
}

function previewMentionText() {
  const parsed = parseSpaceList(contentForm.mentions || (selectedTask.value?.mentions || []).join(' '))
  return parsed.join(' ')
}

function previewPackageText() {
  const lines = [
    previewCaptionText(),
    previewHashtagText(),
    previewMentionText(),
    normalizeQuickNote(contentForm.quick_note || selectedTask.value?.quick_note || '')
  ].filter(Boolean)
  return lines.join('\n').trim()
}

function previewQuickNote(value, maxLength = 84) {
  const normalized = normalizeQuickNote(value)
  if (!normalized) return ''
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, Math.max(1, maxLength - 1))}…`
}

function openNotePreview(task, source = 'board') {
  const note = normalizeQuickNote(task?.quick_note)
  if (!note) return
  const color = taskNoteColor(task)
  notePreview.open = true
  notePreview.taskId = String(task?.id || '')
  notePreview.title = task?.title || 'Untitled task'
  notePreview.note = note
  notePreview.savedColor = color
  notePreview.color = color
  notePreview.draft = note
  notePreview.airDate = task?.air_date || null
  notePreview.source = source
}

function closeNotePreview() {
  notePreview.open = false
  notePreview.taskId = ''
  notePreview.title = ''
  notePreview.note = ''
  notePreview.color = DEFAULT_NOTE_COLOR
  notePreview.savedColor = DEFAULT_NOTE_COLOR
  notePreview.draft = ''
  notePreview.airDate = null
  notePreview.source = ''
  notePreview.saving = false
}

function openTaskFromNotePreview() {
  const taskId = notePreview.taskId
  closeNotePreview()
  if (!taskId) return
  openTask(taskId)
}

function applyQuickNoteToLocalState(taskId, noteValue, noteColor = undefined) {
  const normalizedColor = noteColor === undefined ? undefined : sanitizeHexColor(noteColor, DEFAULT_NOTE_COLOR)
  calendarTasks.value = calendarTasks.value.map((task) =>
    task.id === taskId
      ? { ...task, quick_note: noteValue, ...(normalizedColor === undefined ? {} : { note_color: normalizedColor }) }
      : task
  )

  const nextKanban = {}
  statusOrder.forEach((status) => {
    nextKanban[status] = (kanban.value[status] || []).map((task) =>
      task.id === taskId
        ? { ...task, quick_note: noteValue, ...(normalizedColor === undefined ? {} : { note_color: normalizedColor }) }
        : task
    )
  })
  kanban.value = nextKanban

  if (selectedTask.value?.id === taskId) {
    selectedTask.value = {
      ...selectedTask.value,
      quick_note: noteValue,
      ...(normalizedColor === undefined ? {} : { note_color: normalizedColor }),
    }
    contentForm.quick_note = noteValue || ''
    if (normalizedColor !== undefined) {
      contentForm.note_color = normalizedColor
    }
  }
}

async function saveNoteFromPreview() {
  if (!notePreview.taskId) return
  const normalizedDraft = normalizeQuickNote(notePreview.draft)
  const normalizedCurrent = normalizeQuickNote(notePreview.note)
  const normalizedColor = sanitizeHexColor(notePreview.color, DEFAULT_NOTE_COLOR)
  const normalizedCurrentColor = sanitizeHexColor(notePreview.savedColor, DEFAULT_NOTE_COLOR)
  if (normalizedDraft === normalizedCurrent && normalizedColor === normalizedCurrentColor) {
    showToast('No note changes yet')
    return
  }
  try {
    notePreview.saving = true
    await requestJson(`/tasks/${notePreview.taskId}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'PATCH',
      body: {
        quick_note: normalizedDraft || null,
        note_color: normalizedColor
      }
    })
    notePreview.note = normalizedDraft
    notePreview.savedColor = normalizedColor
    notePreview.color = normalizedColor
    notePreview.draft = normalizedDraft
    applyQuickNoteToLocalState(notePreview.taskId, normalizedDraft || null, normalizedColor)
    showToast('Quick note saved')
    closeNotePreview()
  } catch (error) {
    showToast(`Save note failed (${error.message})`, true)
  } finally {
    notePreview.saving = false
  }
}

function loadTimelinePrefs() {
  try {
    const raw = localStorage.getItem(TIMELINE_PREFS_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    timelinePrefs.dayWidth = clamp(Number(parsed?.dayWidth || timelinePrefs.dayWidth), 140, 320)
    timelinePrefs.cardScale = clamp(Number(parsed?.cardScale || timelinePrefs.cardScale), 90, 200)
  } catch {
    // ignore invalid localStorage
  }
}

function focusTimelineToToday() {
  const viewport = timelineViewportRef.value
  if (!viewport || timeline.value.totalDays <= 0 || viewport.clientWidth <= 0) return false
  const index = clamp(Number(timeline.value.todayIndex || 0), 0, Math.max(timeline.value.totalDays - 1, 0))
  const centered = index * timeline.value.dayWidth - Math.max(0, Math.round((viewport.clientWidth - timeline.value.dayWidth) / 2))
  viewport.scrollLeft = Math.max(0, centered)
  return true
}

function tryAutoFocusTimeline() {
  if (timelineAutoFocusDone.value) return
  nextTick(() => {
    if (timelineAutoFocusDone.value) return
    timelineAutoFocusDone.value = focusTimelineToToday()
  })
}

function startTimelinePan(event) {
  if (event.button !== 0) return
  if (event.target?.closest?.('.timeline-item, .timeline-create-overlay, .timeline-create-btn, button, input, textarea, select, a, label')) return
  if (!timelineViewportRef.value) return
  timelinePanState.active = true
  timelinePanState.startX = event.clientX
  timelinePanState.startScrollLeft = timelineViewportRef.value.scrollLeft
}

function moveTimelinePan(event) {
  if (!timelinePanState.active) return
  if (!timelineViewportRef.value) return
  const delta = event.clientX - timelinePanState.startX
  timelineViewportRef.value.scrollLeft = timelinePanState.startScrollLeft - delta
}

function endTimelinePan() {
  timelinePanState.active = false
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('file_read_failed'))
    reader.readAsDataURL(file)
  })
}

async function fileToBase64Payload(file) {
  if (!file) throw new Error('missing_file')
  const raw = await readFileAsDataUrl(file)
  const [, dataBase64] = String(raw || '').split(',', 2)
  if (!dataBase64) throw new Error('invalid_file_payload')
  return {
    filename: file.name || 'avatar.png',
    content_type: file.type || null,
    data_base64: dataBase64
  }
}

function inferMediaKind(file) {
  return String(file?.type || '').startsWith('video/') ? 'video' : 'image'
}

function fileSignature(file) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function createClientId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID()
  }
  return `tmp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function mapFilesToPendingItems(fileList) {
  const files = Array.from(fileList || [])
  return files.map((file) => ({
    id: createClientId(),
    file,
    signature: fileSignature(file),
    kind: inferMediaKind(file),
    preview_url: URL.createObjectURL(file),
  }))
}

function clearPendingMedia(listRef) {
  listRef.value.forEach((item) => URL.revokeObjectURL(item.preview_url))
  listRef.value = []
}

function removePendingMedia(listRef, itemId) {
  const target = listRef.value.find((item) => item.id === itemId)
  if (target) URL.revokeObjectURL(target.preview_url)
  listRef.value = listRef.value.filter((item) => item.id !== itemId)
}

function appendPendingMedia(fileList, listRef) {
  const incoming = mapFilesToPendingItems(fileList)
  if (incoming.length === 0) return
  const existing = new Set(listRef.value.map((item) => item.signature))
  const deduped = incoming.filter((item) => !existing.has(item.signature))
  if (deduped.length === 0) return
  listRef.value = [...listRef.value, ...deduped]
  showToast(`${deduped.length} file(s) added`)
}

function onDetailMediaFilesChange(event) {
  appendPendingMedia(event.target.files, detailPendingMedia)
  event.target.value = ''
}

function onDetailMediaDrop(event) {
  appendPendingMedia(event.dataTransfer?.files, detailPendingMedia)
}

function onDetailMediaPaste(event) {
  appendPendingMedia(event.clipboardData?.files, detailPendingMedia)
}

function onCommentMediaFilesChange(event) {
  appendPendingMedia(event.target.files, commentPendingMedia)
  event.target.value = ''
}

function showToast(message, isError = false) {
  toast.show = true
  toast.message = message
  toast.error = isError
  if (toast.timer) {
    clearTimeout(toast.timer)
  }
  toast.timer = setTimeout(() => {
    toast.show = false
    toast.error = false
    toast.message = ''
  }, 2500)
}

async function requestJson(url, options = {}) {
  const init = { ...options }
  init.headers = { ...(init.headers || {}) }
  if (auth.token) {
    init.headers.Authorization = `Bearer ${auth.token}`
  }
  if (init.body && typeof init.body !== 'string') {
    init.body = JSON.stringify(init.body)
    init.headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(url, init)
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = data?.detail ? `: ${data.detail}` : ''
    throw new Error(`${response.status}${detail}`)
  }
  return data
}

async function uploadPendingMedia(taskId, pendingItems, actor = null) {
  if (!pendingItems || pendingItems.length === 0) return null
  const files = []
  for (const item of pendingItems) {
    const raw = await readFileAsDataUrl(item.file)
    const [, base64Payload] = String(raw).split(',', 2)
    if (!base64Payload) continue
    files.push({
      filename: item.file.name,
      content_type: item.file.type || null,
      data_base64: base64Payload,
    })
  }
  if (files.length === 0) return null
  const suffix = actor ? `?actor_name=${encodeURIComponent(actor)}` : ''
  return requestJson(`/tasks/${taskId}/assets/base64${suffix}`, {
    method: 'POST',
    body: { files }
  })
}

function actorName() {
  return auth.user?.username || 'dashboard-ui'
}

function saveAuthState() {
  if (!auth.token || !auth.user) {
    localStorage.removeItem(AUTH_STORAGE_KEY)
    return
  }
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token: auth.token, user: auth.user }))
}

function clearAuthState() {
  auth.token = ''
  auth.user = null
  auth.username = ''
  auth.password = ''
  profileForm.name = ''
  profileForm.username = ''
  profileForm.avatar_url = ''
  profileForm.zalo_user_id = ''
  userEditor.zalo_user_id = ''
  zaloSettingsForm.social_group_chat_id = ''
  zaloSettingsForm.source = 'none'
  profileAvatarFile.value = null
  newUserAvatarFile.value = null
  Object.keys(rowAvatarFiles).forEach((userId) => {
    delete rowAvatarFiles[userId]
  })
  timelineAutoFocusDone.value = false
  closeNotePreview()
  saveAuthState()
}

async function login() {
  if (!auth.username.trim() || !auth.password) {
    showToast('Username and password are required', true)
    return
  }
  try {
    authLoading.value = true
    const result = await requestJson('/auth/login', {
      method: 'POST',
      body: { username: auth.username.trim(), password: auth.password }
    })
    auth.token = result.access_token || ''
    auth.user = result.user
      ? {
          ...result.user,
          name: result.user.name || result.user.username || '',
          avatar_url: result.user.avatar_url || '',
          zalo_user_id: result.user.zalo_user_id || ''
        }
      : null
    syncProfileForm()
    saveAuthState()
    await bootstrapAfterAuth()
    auth.password = ''
  } catch (error) {
    clearAuthState()
    showToast(`Login failed (${error.message})`, true)
  } finally {
    authLoading.value = false
  }
}

async function refreshMe() {
  if (!auth.token) return false
  try {
    const me = await requestJson('/auth/me')
    auth.user = {
      id: me.user_id,
      username: me.username,
      name: me.name || me.username,
      role: me.role,
      avatar_url: me.avatar_url || '',
      zalo_user_id: auth.user?.zalo_user_id || ''
    }
    syncProfileForm()
    saveAuthState()
    return true
  } catch {
    clearAuthState()
    return false
  }
}

function logout() {
  clearAuthState()
  showToast('Logged out')
}

function openProfileSettings() {
  syncProfileForm()
  passwordForm.current_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  profileAvatarFile.value = null
  if (isAdmin.value) {
    loadZaloSettings()
  }
  settingsOpen.value = true
}

function onProfileAvatarChange(event) {
  const file = event?.target?.files?.[0] || null
  profileAvatarFile.value = file
}

function onNewUserAvatarChange(event) {
  const file = event?.target?.files?.[0] || null
  newUserAvatarFile.value = file
}

function onManagedUserAvatarChange(userId, event) {
  const file = event?.target?.files?.[0] || null
  if (!file) {
    delete rowAvatarFiles[userId]
    return
  }
  rowAvatarFiles[userId] = file
}

function toggleAssigneePicker() {
  assigneePickerOpen.value = !assigneePickerOpen.value
}

function closeAssigneePicker() {
  assigneePickerOpen.value = false
}

function chooseAssignee(value) {
  contentForm.assignee_name = String(value || '').trim()
  assigneePickerOpen.value = false
}

function assignToMe() {
  chooseAssignee(auth.user?.name || auth.user?.username || '')
}

function handlePointerDown(event) {
  if (!assigneePickerOpen.value) return
  const root = assigneePickerRef.value
  if (root && !root.contains(event.target)) {
    assigneePickerOpen.value = false
  }
}

async function loadCampaigns() {
  if (!auth.token) return
  try {
    campaigns.value = await requestJson('/campaigns')
  } catch {
    campaigns.value = []
  }
}

function hydrateUserRows() {
  userRows.value = users.value.map((user) => ({
    id: user.id,
    name: user.name || '',
    username: user.username || '',
    role: user.role || 'content',
    avatar_url: user.avatar_url || '',
    zalo_user_id: user.zalo_user_id || '',
    is_active: Boolean(user.is_active),
    temp_password: ''
  }))
  const validIds = new Set(userRows.value.map((row) => row.id))
  Object.keys(rowAvatarFiles).forEach((userId) => {
    if (!validIds.has(userId)) {
      delete rowAvatarFiles[userId]
    }
  })
}

async function loadUsers(includeInactive = true) {
  if (!auth.token) return
  try {
    usersLoading.value = true
    const query = includeInactive ? '?include_inactive=true' : ''
    users.value = await requestJson(`/users${query}`)
    hydrateUserRows()
  } catch {
    users.value = []
    userRows.value = []
  } finally {
    usersLoading.value = false
  }
}

async function loadZaloSettings() {
  if (!auth.token || !isAdmin.value) return
  try {
    const payload = await requestJson('/settings/zalo')
    zaloSettingsForm.social_group_chat_id = payload?.social_group_chat_id || ''
    zaloSettingsForm.source = payload?.source || 'none'
  } catch {
    zaloSettingsForm.social_group_chat_id = ''
    zaloSettingsForm.source = 'none'
  }
}

function syncProfileForm() {
  profileForm.name = auth.user?.name || ''
  profileForm.username = auth.user?.username || ''
  profileForm.avatar_url = auth.user?.avatar_url || ''
  profileForm.zalo_user_id = auth.user?.zalo_user_id || ''
}

async function loadProfile() {
  if (!auth.token) return
  try {
    const me = await requestJson('/profile')
    auth.user = {
      id: me.id,
      username: me.username || auth.user?.username || '',
      name: me.name || '',
      role: me.role || auth.user?.role || 'content',
      avatar_url: me.avatar_url || '',
      zalo_user_id: me.zalo_user_id || ''
    }
    saveAuthState()
    syncProfileForm()
  } catch {
    syncProfileForm()
  }
}

async function saveProfile() {
  try {
    profileSaving.value = true
    const updated = await requestJson('/profile', {
      method: 'PATCH',
      body: {
        name: profileForm.name.trim() || null,
        username: profileForm.username.trim() || null,
        zalo_user_id: profileForm.zalo_user_id.trim() || null
      }
    })
    auth.user = {
      ...auth.user,
      id: updated.id,
      username: updated.username || auth.user?.username || '',
      name: updated.name || '',
      role: updated.role || auth.user?.role || 'content',
      avatar_url: updated.avatar_url || '',
      zalo_user_id: updated.zalo_user_id || ''
    }
    saveAuthState()
    await loadUsers(isAdmin.value)
    syncProfileForm()
    showToast('Profile saved')
    settingsOpen.value = false
  } catch (error) {
    showToast(`Save profile failed (${error.message})`, true)
  } finally {
    profileSaving.value = false
  }
}

async function uploadProfileAvatar() {
  if (!profileAvatarFile.value) {
    showToast('Choose an avatar file first', true)
    return
  }
  try {
    profileSaving.value = true
    const filePayload = await fileToBase64Payload(profileAvatarFile.value)
    const updated = await requestJson('/profile/avatar', {
      method: 'PUT',
      body: { file: filePayload }
    })
    auth.user = {
      ...auth.user,
      avatar_url: updated.avatar_url || ''
    }
    profileForm.avatar_url = updated.avatar_url || ''
    profileAvatarFile.value = null
    saveAuthState()
    await loadUsers(isAdmin.value)
    showToast('Avatar uploaded')
  } catch (error) {
    showToast(`Upload avatar failed (${error.message})`, true)
  } finally {
    profileSaving.value = false
  }
}

async function saveMyPassword() {
  if (!passwordForm.new_password) {
    showToast('Enter new password', true)
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    showToast('Password confirmation mismatch', true)
    return
  }
  try {
    passwordSaving.value = true
    await requestJson('/profile/password', {
      method: 'PUT',
      body: {
        current_password: passwordForm.current_password,
        new_password: passwordForm.new_password
      }
    })
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
    showToast('Password updated')
    settingsOpen.value = false
  } catch (error) {
    showToast(`Change password failed (${error.message})`, true)
  } finally {
    passwordSaving.value = false
  }
}

async function saveZaloSettings() {
  if (!isAdmin.value) return
  try {
    zaloSettingsSaving.value = true
    const payload = await requestJson('/settings/zalo', {
      method: 'PATCH',
      body: {
        social_group_chat_id: zaloSettingsForm.social_group_chat_id.trim() || null
      }
    })
    zaloSettingsForm.social_group_chat_id = payload?.social_group_chat_id || ''
    zaloSettingsForm.source = payload?.source || 'none'
    showToast('Zalo settings saved')
  } catch (error) {
    showToast(`Save Zalo settings failed (${error.message})`, true)
  } finally {
    zaloSettingsSaving.value = false
  }
}

async function testZaloSettings() {
  if (!isAdmin.value) return
  try {
    zaloTestSending.value = true
    const result = await requestJson('/settings/zalo/test', { method: 'POST' })
    const sent = Number(result?.sent || 0)
    const failed = Number(result?.failed || 0)
    if (failed > 0) {
      showToast(`Test sent ${sent}, failed ${failed}`, true)
      return
    }
    showToast(`Test sent ${sent} message(s)`)
  } catch (error) {
    showToast(`Test Zalo failed (${error.message})`, true)
  } finally {
    zaloTestSending.value = false
  }
}

function resetCampaignEditor() {
  campaignEditor.editingId = ''
  campaignEditor.name = ''
  campaignEditor.status = 'planning'
  campaignEditor.start_date = ''
  campaignEditor.end_date = ''
  campaignEditor.link_url = ''
  campaignEditor.description = ''
  campaignEditor.color = DEFAULT_CAMPAIGN_COLOR
  campaignEditor.icon = DEFAULT_CAMPAIGN_ICON
  campaignEditor.requires_product_url = false
  campaignEditor.brand = ''
  campaignEditor.platform = ''
}

function openCampaignCreate() {
  resetCampaignEditor()
  campaignEditor.open = true
}

function openCampaignEdit(campaign) {
  campaignEditor.editingId = String(campaign?.id || '')
  campaignEditor.name = campaign?.name || ''
  campaignEditor.status = campaign?.status || 'planning'
  campaignEditor.start_date = campaign?.start_date || ''
  campaignEditor.end_date = campaign?.end_date || ''
  campaignEditor.link_url = campaign?.link_url || ''
  campaignEditor.description = campaign?.description || ''
  campaignEditor.color = sanitizeCampaignColor(campaign?.color, DEFAULT_CAMPAIGN_COLOR)
  campaignEditor.icon = normalizeCampaignIcon(campaign?.icon, DEFAULT_CAMPAIGN_ICON)
  campaignEditor.requires_product_url = Boolean(campaign?.requires_product_url)
  campaignEditor.brand = campaign?.brand || ''
  campaignEditor.platform = campaign?.platform || ''
  campaignEditor.open = true
}

function closeCampaignEditor() {
  campaignEditor.open = false
  campaignEditor.saving = false
}

async function saveCampaign() {
  const name = campaignEditor.name.trim()
  if (!name) {
    showToast('Campaign name is required', true)
    return
  }
  const payload = {
    name,
    status: (campaignEditor.status || 'planning').trim() || 'planning',
    start_date: campaignEditor.start_date || null,
    end_date: campaignEditor.end_date || null,
    link_url: campaignEditor.link_url.trim() || null,
    description: campaignEditor.description.trim() || null,
    color: sanitizeCampaignColor(campaignEditor.color),
    icon: normalizeCampaignIcon(campaignEditor.icon),
    requires_product_url: Boolean(campaignEditor.requires_product_url),
    brand: campaignEditor.brand.trim() || null,
    platform: campaignEditor.platform.trim() || null
  }
  try {
    campaignEditor.saving = true
    if (campaignEditor.editingId) {
      await requestJson(`/campaigns/${campaignEditor.editingId}`, { method: 'PATCH', body: payload })
      showToast('Campaign updated')
    } else {
      await requestJson('/campaigns', { method: 'POST', body: payload })
      showToast('Campaign created')
    }
    closeCampaignEditor()
    await Promise.all([loadCampaigns(), loadDashboard()])
  } catch (error) {
    showToast(`Save campaign failed (${error.message})`, true)
  } finally {
    campaignEditor.saving = false
  }
}

async function removeCampaign(campaignId) {
  if (!window.confirm('Delete this campaign?')) return
  try {
    await requestJson(`/campaigns/${campaignId}`, { method: 'DELETE' })
    if (campaignEditor.editingId === campaignId) {
      closeCampaignEditor()
    }
    if (contentForm.campaign_name && campaigns.value.find((row) => row.id === campaignId)?.name === contentForm.campaign_name) {
      contentForm.campaign_name = ''
    }
    await Promise.all([loadCampaigns(), loadDashboard()])
    showToast('Campaign deleted')
  } catch (error) {
    showToast(`Delete campaign failed (${error.message})`, true)
  }
}

function campaignDateRange(campaign) {
  const start = String(campaign?.start_date || '').trim()
  const end = String(campaign?.end_date || '').trim()
  if (start && end) return `${start} → ${end}`
  if (start) return `From ${start}`
  if (end) return `Until ${end}`
  return 'No date range'
}

async function bootstrapAfterAuth() {
  await loadProfile()
  await Promise.all([loadDashboard(), loadCampaigns(), loadUsers(isAdmin.value)])
  if (isAdmin.value) {
    await loadZaloSettings()
  }
  openFromPath()
  tryAutoFocusTimeline()
}

function openUsersView() {
  activeView.value = 'users'
  safePushState(buildDashboardUrl('users'))
}

async function createManagedUser() {
  const name = userEditor.name.trim()
  const username = userEditor.username.trim().toLowerCase()
  if (!name || !username || !userEditor.password) {
    showToast('Name, username and password are required', true)
    return
  }
  try {
    const created = await requestJson('/users', {
      method: 'POST',
      body: {
        name,
        username,
        role: userEditor.role.trim() || 'content',
        zalo_user_id: userEditor.zalo_user_id.trim() || null,
        password: userEditor.password,
        is_active: true
      }
    })
    if (newUserAvatarFile.value) {
      const filePayload = await fileToBase64Payload(newUserAvatarFile.value)
      await requestJson(`/users/${created.id}/avatar`, {
        method: 'PUT',
        body: { file: filePayload }
      })
    }
    userEditor.name = ''
    userEditor.username = ''
    userEditor.role = 'content'
    userEditor.zalo_user_id = ''
    userEditor.password = ''
    newUserAvatarFile.value = null
    await loadUsers(true)
    showToast('User created')
  } catch (error) {
    showToast(`Create user failed (${error.message})`, true)
  }
}

async function saveManagedUser(row) {
  try {
    await requestJson(`/users/${row.id}`, {
      method: 'PATCH',
      body: {
        name: row.name.trim(),
        username: row.username.trim().toLowerCase(),
        role: row.role.trim() || 'content',
        zalo_user_id: String(row.zalo_user_id || '').trim() || null,
        is_active: Boolean(row.is_active)
      }
    })
    if (auth.user?.id === row.id) {
      await loadProfile()
    }
    await loadUsers(true)
    showToast('User saved')
  } catch (error) {
    showToast(`Save user failed (${error.message})`, true)
  }
}

async function uploadManagedUserAvatar(row) {
  const file = rowAvatarFiles[row.id]
  if (!file) {
    showToast('Choose avatar file for this user first', true)
    return
  }
  try {
    const filePayload = await fileToBase64Payload(file)
    await requestJson(`/users/${row.id}/avatar`, {
      method: 'PUT',
      body: { file: filePayload }
    })
    delete rowAvatarFiles[row.id]
    await loadUsers(true)
    if (auth.user?.id === row.id) {
      await loadProfile()
    }
    showToast('Avatar updated')
  } catch (error) {
    showToast(`Upload avatar failed (${error.message})`, true)
  }
}

async function saveManagedUserPassword(row) {
  const newPassword = String(row.temp_password || '')
  if (!newPassword) {
    showToast('Enter new password first', true)
    return
  }
  try {
    await requestJson(`/users/${row.id}/password`, {
      method: 'PUT',
      body: { password: newPassword }
    })
    row.temp_password = ''
    showToast('Password updated')
  } catch (error) {
    showToast(`Set password failed (${error.message})`, true)
  }
}

async function removeManagedUser(row) {
  if (!window.confirm(`Disable user ${row.name || row.username}?`)) return
  try {
    await requestJson(`/users/${row.id}`, { method: 'DELETE' })
    if (auth.user?.id === row.id) {
      logout()
      return
    }
    await loadUsers(true)
    showToast('User disabled')
  } catch (error) {
    showToast(`Disable user failed (${error.message})`, true)
  }
}

const flatTasks = computed(() => statusOrder.flatMap((status) => kanban.value[status] || []))

const summaryById = computed(() => {
  const map = new Map()
  flatTasks.value.forEach((task) => map.set(task.id, task))
  return map
})

const isAdmin = computed(() => String(auth.user?.role || '').toLowerCase() === 'admin')

const currentUserAvatar = computed(() => auth.user?.avatar_url || '')

const heroBadges = computed(() => [
  `This week: ${analytics.value.total_this_week ?? 0}`,
  `Overdue: ${analytics.value.overdue_count ?? 0}`,
  `Campaigns: ${analytics.value.campaign_count ?? 0}`,
  `Assignees: ${new Set(flatTasks.value.map((task) => task.assignee).filter(Boolean)).size}`
])

const metrics = computed(() => {
  const now = new Date()
  const upcoming = flatTasks.value.filter((task) => task.status !== 'posted' && task.air_date && new Date(task.air_date) >= now).length
  const inProgress = flatTasks.value.filter((task) => task.status === 'design' || task.status === 'ready').length
  const completed = flatTasks.value.filter((task) => task.status === 'posted').length
  return { upcoming, inProgress, completed }
})

const sortedMessages = computed(() => {
  return [...flatTasks.value]
    .sort((a, b) => new Date(b.air_date || 0).valueOf() - new Date(a.air_date || 0).valueOf())
    .slice(0, 6)
})

const todayItems = computed(() => {
  const todayKey = onlyDateKey(new Date().toISOString())
  return calendarTasks.value.filter((task) => onlyDateKey(task.air_date) === todayKey)
})

const assigneeUsers = computed(() => {
  const map = new Map()
  users.value.forEach((user) => {
    if (!user?.is_active) return
    const displayName = String(user.name || user.username || '').trim()
    if (!displayName) return
    map.set(nameKey(displayName), {
      id: user.id || `user-${displayName}`,
      name: displayName,
      avatar_url: user.avatar_url || ''
    })
  })
  flatTasks.value.forEach((task) => {
    const displayName = String(task.assignee || '').trim()
    if (!displayName) return
    const key = nameKey(displayName)
    if (!map.has(key)) {
      map.set(key, {
        id: `task-${displayName}`,
        name: displayName,
        avatar_url: assigneeAvatarUrl(displayName)
      })
    }
  })
  if (contentForm.assignee_name) {
    const displayName = contentForm.assignee_name.trim()
    const key = nameKey(displayName)
    if (displayName && !map.has(key)) {
      map.set(key, {
        id: `current-${displayName}`,
        name: displayName,
        avatar_url: assigneeAvatarUrl(displayName)
      })
    }
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name))
})

const selectedAssigneeUser = computed(() => {
  const key = nameKey(contentForm.assignee_name)
  if (!key) return null
  return assigneeUsers.value.find((user) => nameKey(user.name) === key) || null
})

const selectedTaskAssets = computed(() => {
  return (selectedTask.value?.assets || []).filter((item) => !isDemoAssetUrl(item.url))
})

const previewAssets = computed(() => selectedTaskAssets.value)

const previewCurrentIndex = computed(() => {
  return clamp(previewCarouselIndex.value, 0, Math.max(previewAssets.value.length - 1, 0))
})

const previewCurrentAsset = computed(() => {
  if (previewAssets.value.length === 0) return null
  return previewAssets.value[previewCurrentIndex.value] || null
})

const previewQuickNoteText = computed(() => {
  return normalizeQuickNote(contentForm.quick_note || selectedTask.value?.quick_note || '')
})

const previewFieldCards = computed(() => {
  return [
    { key: 'caption', label: 'Caption', value: previewCaptionText(), emptyLabel: 'No caption' },
    { key: 'hashtags', label: 'Hashtags', value: previewHashtagText(), emptyLabel: 'No hashtags' },
    { key: 'mentions', label: 'Mentions', value: previewMentionText(), emptyLabel: 'No mentions' },
    { key: 'quick_note', label: 'Quick note', value: previewQuickNoteText.value, emptyLabel: 'No quick note' },
  ]
})

const previewPublicUrl = computed(() => {
  const raw = String(previewLinkState.data?.preview_url || '').trim()
  if (!raw) return ''
  try {
    return new URL(raw, window.location.origin).toString()
  } catch {
    return raw
  }
})

const campaignOptions = computed(() => {
  const rows = [...campaigns.value].sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
  const current = contentForm.campaign_name.trim()
  if (current && !rows.some((row) => row.name === current)) {
    rows.unshift({ id: `custom-${current}`, name: current })
  }
  return rows
})

const campaignByName = computed(() => {
  const map = new Map()
  campaigns.value.forEach((campaign) => {
    const key = nameKey(campaign?.name)
    if (!key) return
    map.set(key, campaign)
  })
  return map
})

function campaignThemeByName(campaignName) {
  const key = nameKey(campaignName)
  if (!key) return null
  const found = campaignByName.value.get(key)
  if (!found) return null
  return {
    color: sanitizeCampaignColor(found.color),
    icon: normalizeCampaignIcon(found.icon),
    name: found.name || campaignName
  }
}

function campaignThemeFromTask(task) {
  if (!task?.campaign) return null
  const byName = campaignThemeByName(task.campaign)
  return {
    name: task.campaign,
    color: sanitizeCampaignColor(task.campaign_color || byName?.color || DEFAULT_CAMPAIGN_COLOR),
    icon: normalizeCampaignIcon(task.campaign_icon || byName?.icon || DEFAULT_CAMPAIGN_ICON)
  }
}

function campaignAccentStyle(task) {
  const theme = campaignThemeFromTask(task)
  if (!theme) return {}
  return { '--campaign-color': theme.color }
}

const timeline = computed(() => {
  const items = calendarTasks.value.filter((row) => row.air_date)
  const campaignRanges = campaigns.value
    .map((campaign) => {
      const startRaw = parseIsoDay(campaign.start_date)
      const endRaw = parseIsoDay(campaign.end_date)
      if (!startRaw && !endRaw) return null
      const startDate = startRaw || endRaw
      const endDate = endRaw || startRaw
      if (!startDate || !endDate) return null
      const from = startDate.valueOf() <= endDate.valueOf() ? startDate : endDate
      const to = startDate.valueOf() <= endDate.valueOf() ? endDate : startDate
      return {
        ...campaign,
        startDate: from,
        endDate: to,
      }
    })
    .filter(Boolean)

  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const taskDates = items
    .map((row) => new Date(row.air_date))
    .filter((date) => !Number.isNaN(date.valueOf()))
  const datePool = [
    now.valueOf(),
    ...taskDates.map((date) => date.valueOf()),
    ...campaignRanges.flatMap((campaign) => [campaign.startDate.valueOf(), campaign.endDate.valueOf()]),
  ]
  const minSource = new Date(Math.min(...datePool))
  const maxSource = new Date(Math.max(...datePool))

  const startDate = new Date(minSource.getFullYear(), minSource.getMonth(), 1)
  const endDate = new Date(maxSource.getFullYear(), maxSource.getMonth() + 1, 0)
  const msPerDay = 24 * 3600 * 1000
  const totalDays = Math.floor((endDate.valueOf() - startDate.valueOf()) / msPerDay) + 1
  const dayWidth = clamp(Math.round(timelinePrefs.dayWidth), 140, 320)
  const scale = clamp(timelinePrefs.cardScale / 100, 0.9, 2)
  const cardHeight = Math.round(258 * scale)
  const rowHeight = cardHeight + 26
  const mediaHeight = Math.round(176 * scale)
  const gridWidth = totalDays * dayWidth
  const createRowHeight = 54
  const campaignRowHeight = 40
  const campaignTopOffset = createRowHeight + 6
  const todayIndex = clamp(Math.floor((todayStart.valueOf() - startDate.valueOf()) / msPerDay), 0, Math.max(totalDays - 1, 0))

  const days = Array.from({ length: totalDays }).map((_, index) => {
    const date = new Date(startDate)
    date.setDate(startDate.getDate() + index)
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return {
      key: `${year}-${month}-${day}`,
      iso: `${year}-${month}-${day}`,
      weekday: new Intl.DateTimeFormat('en-US', { weekday: 'short' }).format(date),
      monthDay: new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(date)
    }
  })

  const campaignLaneEnd = []
  const campaignBars = [...campaignRanges]
    .sort((a, b) => a.startDate.valueOf() - b.startDate.valueOf())
    .map((campaign) => {
      const rawStart = Math.floor((campaign.startDate.valueOf() - startDate.valueOf()) / msPerDay)
      const rawEnd = Math.floor((campaign.endDate.valueOf() - startDate.valueOf()) / msPerDay)
      if (rawEnd < 0 || rawStart > totalDays - 1) return null

      const startIndex = clamp(rawStart, 0, totalDays - 1)
      const endIndex = clamp(rawEnd, 0, totalDays - 1)
      const spanDays = Math.max(1, endIndex - startIndex + 1)

      let lane = campaignLaneEnd.findIndex((value) => startIndex > value)
      if (lane === -1) {
        lane = campaignLaneEnd.length
        campaignLaneEnd.push(-1)
      }
      campaignLaneEnd[lane] = endIndex

      return {
        id: campaign.id,
        name: campaign.name,
        status: campaign.status || 'planning',
        icon: normalizeCampaignIcon(campaign.icon, campaignTimelineIcon(campaign.status)),
        color: sanitizeCampaignColor(campaign.color, DEFAULT_CAMPAIGN_COLOR),
        style: {
          top: `${campaignTopOffset + lane * campaignRowHeight}px`,
          left: `${startIndex * dayWidth + 10}px`,
          width: `${Math.max(160, spanDays * dayWidth - 20)}px`,
          '--campaign-color': sanitizeCampaignColor(campaign.color, DEFAULT_CAMPAIGN_COLOR),
        }
      }
    })
    .filter(Boolean)

  const campaignSectionHeight = campaignBars.length > 0 ? campaignBars.length * campaignRowHeight + 8 : 0
  const laneTopOffset = createRowHeight + campaignSectionHeight + 10

  const laneEnd = []
  const cards = [...items]
    .sort((a, b) => new Date(a.air_date).valueOf() - new Date(b.air_date).valueOf())
    .map((task) => {
      const date = new Date(task.air_date)
      const dayIndex = Math.floor((date.valueOf() - startDate.valueOf()) / msPerDay)
      if (dayIndex < 0 || dayIndex > totalDays - 1) return null

      const logicalDuration = 1
      const laneWidth = logicalDuration * dayWidth
      const widthPx = clamp(laneWidth - 12, Math.round(dayWidth * 0.8), laneWidth - 8)
      const end = dayIndex + logicalDuration
      // A card with one-day span should allow the next day to reuse the same lane.
      let lane = laneEnd.findIndex((value) => dayIndex >= value - 0.01)
      if (lane === -1) {
        lane = laneEnd.length
        laneEnd.push(Number.NEGATIVE_INFINITY)
      }
      laneEnd[lane] = end

      const summary = summaryById.value.get(task.id)
      return {
        ...task,
        media_thumbnail: summary?.media_thumbnail || task.media_thumbnail || null,
        style: {
          top: `${laneTopOffset + lane * rowHeight}px`,
          left: `${dayIndex * dayWidth + 8}px`,
          width: `${widthPx}px`
        }
      }
    })
    .filter(Boolean)

  return {
    days,
    campaignBars,
    campaignRowHeight,
    cards,
    laneCount: Math.max(laneEnd.length, 1),
    dayWidth,
    rowHeight,
    cardHeight,
    mediaHeight,
    createRowHeight,
    laneTopOffset,
    totalDays,
    gridWidth,
    todayIndex
  }
})

function statusClass(status) {
  return `status-${status}`
}

function typeClass(type) {
  return `type-${type}`
}

function cardBadges(task) {
  const badges = []
  if (visibleFields.type) badges.push({ text: String(task.type || '').toUpperCase(), className: typeClass(task.type) })
  if (visibleFields.airDate) badges.push({ text: `📅 ${fmtDate(task.air_date, false)}`, className: '' })
  return badges
}

async function loadDashboard() {
  if (!auth.token) return
  try {
    loading.value = true
    const [kanbanData, calendarData, analyticsData] = await Promise.all([
      requestJson('/dashboard/kanban'),
      requestJson('/dashboard/calendar'),
      requestJson('/analytics/basic')
    ])
    kanban.value = kanbanData
    calendarTasks.value = calendarData
    analytics.value = analyticsData
  } catch (error) {
    showToast(`Failed to load dashboard (${error.message})`, true)
  } finally {
    loading.value = false
  }
}

function dashboardBasePath() {
  const path = String(window.location.pathname || '')
  if (path.startsWith('/social/dashboard')) return '/social/dashboard'
  if (path === '/social' || path.startsWith('/social/')) return '/social/dashboard'
  if (path.startsWith('/dashboard')) return '/dashboard'
  return '/dashboard'
}

function buildDashboardUrl(suffix = '') {
  const base = dashboardBasePath().replace(/\/+$/, '')
  const cleanSuffix = String(suffix || '').replace(/^\/+/, '')
  return cleanSuffix ? `${base}/${cleanSuffix}` : base
}

function safePushState(url) {
  let next = String(url || '').trim()
  if (!next) next = '/dashboard'
  if (next.startsWith('//')) next = `/dashboard/${next.replace(/^\/+/, '')}`
  if (!next.startsWith('/')) next = `/${next}`
  try {
    window.history.pushState({}, '', next)
    return true
  } catch (error) {
    console.warn('history_push_failed', next, error)
    return false
  }
}

function openOverviewSection(targetId = null) {
  activeView.value = 'overview'
  safePushState(buildDashboardUrl())
  if (!targetId) return
  nextTick(() => {
    const el = document.getElementById(targetId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

function openCampaignsView() {
  activeView.value = 'campaigns'
  safePushState(buildDashboardUrl('campaigns'))
}

function toDateTimeInputFromIsoDay(dayIso, hour = 19, minute = 0) {
  const [y, m, d] = String(dayIso || '')
    .split('-')
    .map((part) => Number(part))
  if (![y, m, d].every((value) => Number.isFinite(value) && value > 0)) return ''
  const pad = (value) => String(value).padStart(2, '0')
  return `${String(y).padStart(4, '0')}-${pad(m)}-${pad(d)}T${pad(hour)}:${pad(minute)}`
}

function resetDetailDraft(defaultStatus = 'idea') {
  contentForm.title = ''
  contentForm.quick_note = ''
  contentForm.note_color = DEFAULT_NOTE_COLOR
  contentForm.caption = ''
  contentForm.hashtags = ''
  contentForm.mentions = ''
  contentForm.assignee_name = ''
  contentForm.campaign_name = ''
  contentForm.air_date = ''
  checklistText.value = ''
  commentText.value = ''
  statusValue.value = statusOrder.includes(defaultStatus) ? defaultStatus : 'idea'
  createType.value = 'story'
  clearPendingMedia(detailPendingMedia)
  clearPendingMedia(commentPendingMedia)
}

function openCreateInColumn(defaultStatus = 'idea') {
  activeView.value = 'overview'
  createMode.value = true
  detailOpen.value = true
  selectedTask.value = null
  selectedTaskId.value = null
  previewLinkState.data = null
  previewCarouselIndex.value = 0
  activeTab.value = 'content'
  resetDetailDraft(defaultStatus)
  safePushState(buildDashboardUrl())
}

function openCreateForTimelineDay(dayIso) {
  openCreateInColumn('idea')
  const defaultDate = toDateTimeInputFromIsoDay(dayIso, 19, 0)
  if (defaultDate) {
    contentForm.air_date = defaultDate
  }
}

async function openTask(taskId, push = true) {
  try {
    const task = await requestJson(`/tasks/${taskId}`)
    activeView.value = 'overview'
    createMode.value = false
    selectedTask.value = task
    selectedTaskId.value = task.id
    detailOpen.value = true
    activeTab.value = 'content'
    previewCarouselIndex.value = 0
    previewLinkState.data = null

    const summary = summaryById.value.get(task.id)
    contentForm.title = task.title || ''
    contentForm.quick_note = normalizeQuickNote(task.quick_note || summary?.quick_note || '')
    contentForm.note_color = sanitizeHexColor(task.note_color || summary?.note_color, DEFAULT_NOTE_COLOR)
    contentForm.caption = task.caption || ''
    contentForm.hashtags = (task.hashtags || []).join(' ')
    contentForm.mentions = (task.mentions || []).join(' ')
    contentForm.assignee_name = task.assignee_name || summary?.assignee || ''
    contentForm.campaign_name = task.campaign_name || summary?.campaign || ''
    contentForm.air_date = toInputDatetime(task.air_date)

    clearPendingMedia(detailPendingMedia)
    clearPendingMedia(commentPendingMedia)

    checklistText.value = (task.checklist_items || [])
      .slice()
      .sort((a, b) => a.position - b.position)
      .map((item) => `${item.is_done ? '[x]' : '[ ]'} ${item.title}`)
      .join('\n')

    commentText.value = ''
    statusValue.value = task.status

    if (push) {
      safePushState(buildDashboardUrl(`tasks/${task.id}`))
    }
  } catch (error) {
    showToast(`Failed to open task (${error.message})`, true)
  }
}

function closeDetail() {
  createMode.value = false
  detailOpen.value = false
  assigneePickerOpen.value = false
  selectedTask.value = null
  selectedTaskId.value = null
  closeNotePreview()
  previewLinkState.data = null
  previewCarouselIndex.value = 0
  clearPendingMedia(detailPendingMedia)
  clearPendingMedia(commentPendingMedia)
  safePushState(buildDashboardUrl())
}

async function refreshAndKeepDetail() {
  const current = selectedTaskId.value
  await loadDashboard()
  if (current) {
    await openTask(current, false)
  }
}

function previewMediaKind(asset) {
  return String(asset?.kind || '').toLowerCase() === 'video' ? 'video' : 'image'
}

function previewMediaLabel() {
  return `${previewCurrentIndex.value + 1}/${Math.max(previewAssets.value.length, 1)}`
}

function previewPrevMedia() {
  if (previewAssets.value.length <= 1) return
  previewCarouselIndex.value = (previewCurrentIndex.value - 1 + previewAssets.value.length) % previewAssets.value.length
}

function previewNextMedia() {
  if (previewAssets.value.length <= 1) return
  previewCarouselIndex.value = (previewCurrentIndex.value + 1) % previewAssets.value.length
}

async function copyPreviewPackage() {
  const packageText = previewPackageText()
  if (!packageText) {
    showToast('No content to copy yet', true)
    return
  }
  try {
    await navigator.clipboard.writeText(packageText)
    showToast('Post package copied')
  } catch {
    showToast('Copy failed', true)
  }
}

async function copyPreviewField(fieldValue, fieldLabel) {
  const text = String(fieldValue || '').trim()
  if (!text) {
    showToast(`No ${String(fieldLabel || 'field').toLowerCase()} to copy`, true)
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    showToast(`${fieldLabel} copied`)
  } catch {
    showToast('Copy failed', true)
  }
}

function triggerMediaDownload(url) {
  const clean = String(url || '').trim()
  if (!clean) return
  const anchor = document.createElement('a')
  anchor.href = clean
  anchor.download = assetFileName(clean)
  anchor.target = '_blank'
  anchor.rel = 'noopener noreferrer'
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
}

function downloadCurrentPreviewMedia() {
  if (!previewCurrentAsset.value?.url) {
    showToast('No media to download', true)
    return
  }
  triggerMediaDownload(previewCurrentAsset.value.url)
}

function downloadAllPreviewMedia() {
  if (previewAssets.value.length === 0) {
    showToast('No media to download', true)
    return
  }
  previewAssets.value.forEach((asset, index) => {
    setTimeout(() => triggerMediaDownload(asset.url), index * 180)
  })
  showToast(`Downloading ${previewAssets.value.length} file(s)`)
}

async function loadTaskPreviewLink() {
  if (createMode.value || !selectedTaskId.value) return
  try {
    previewLinkState.loading = true
    previewLinkState.data = await requestJson(`/tasks/${selectedTaskId.value}/preview-link`)
  } catch {
    previewLinkState.data = null
  } finally {
    previewLinkState.loading = false
  }
}

async function regenerateTaskPreviewLinkAction() {
  if (createMode.value || !selectedTaskId.value) return
  try {
    previewLinkState.generating = true
    previewLinkState.data = await requestJson(`/tasks/${selectedTaskId.value}/preview-link`, {
      method: 'POST'
    })
    showToast('Public preview link generated')
  } catch (error) {
    showToast(`Generate link failed (${error.message})`, true)
  } finally {
    previewLinkState.generating = false
  }
}

function openPreviewPublicLink() {
  if (!previewPublicUrl.value) {
    showToast('No active preview link', true)
    return
  }
  window.open(previewPublicUrl.value, '_blank', 'noopener,noreferrer')
}

async function updateTaskStatus(taskId, status) {
  try {
    await requestJson(`/tasks/${taskId}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'PATCH',
      body: { status }
    })
    showToast(`Task moved to ${statusLabels[status]}`)
    await refreshAndKeepDetail()
  } catch (error) {
    showToast(`Status update failed (${error.message})`, true)
  }
}

function handleStatusSelectChange() {
  if (createMode.value) return
  if (!selectedTaskId.value) return
  updateTaskStatus(selectedTaskId.value, statusValue.value)
}

async function handleCreateFromDetail() {
  if (!contentForm.title.trim()) {
    showToast('Title is required', true)
    return
  }

  const payload = {
    title: contentForm.title.trim(),
    type: createType.value,
    status: statusValue.value,
    air_date: contentForm.air_date || null,
    assignee_name: contentForm.assignee_name.trim() || null,
    campaign_name: contentForm.campaign_name.trim() || null,
    quick_note: normalizeQuickNote(contentForm.quick_note) || null,
    note_color: sanitizeHexColor(contentForm.note_color, DEFAULT_NOTE_COLOR),
    caption: contentForm.caption.trim() || null,
    hashtags: parseSpaceList(contentForm.hashtags),
    mentions: parseSpaceList(contentForm.mentions),
    checklist: parseChecklistLines(checklistText.value),
  }

  try {
    const created = await requestJson('/tasks', { method: 'POST', body: payload })
    if (detailPendingMedia.value.length > 0) {
      await uploadPendingMedia(created.id, detailPendingMedia.value, actorName())
    }
    showToast('Task created')
    await loadDashboard()
    await openTask(created.id)
  } catch (error) {
    showToast(`Create failed (${error.message})`, true)
  }
}

async function handleSaveContent() {
  if (createMode.value) {
    await handleCreateFromDetail()
    return
  }
  if (!selectedTaskId.value) return
  try {
    const payload = {
      title: contentForm.title.trim(),
      quick_note: normalizeQuickNote(contentForm.quick_note),
      note_color: sanitizeHexColor(contentForm.note_color, DEFAULT_NOTE_COLOR),
      caption: contentForm.caption,
      hashtags: parseSpaceList(contentForm.hashtags),
      mentions: parseSpaceList(contentForm.mentions),
      campaign_name: contentForm.campaign_name.trim()
    }
    if (contentForm.assignee_name.trim()) payload.assignee_name = contentForm.assignee_name.trim()
    if (contentForm.air_date) payload.air_date = contentForm.air_date

    await requestJson(`/tasks/${selectedTaskId.value}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'PATCH',
      body: payload
    })
    showToast('Content saved')
    await loadDashboard()
    closeDetail()
  } catch (error) {
    showToast(`Save failed (${error.message})`, true)
  }
}

async function handleAttachMedia() {
  if (createMode.value) {
    if (detailPendingMedia.value.length === 0) {
      showToast('Add media files first', true)
      return
    }
    showToast('Media is queued. Click Save Content to create task.')
    return
  }
  if (!selectedTaskId.value) return
  const pendingFiles = detailPendingMedia.value
  if (pendingFiles.length === 0) {
    showToast('Add media files first', true)
    return
  }
  try {
    if (pendingFiles.length > 0) {
      await uploadPendingMedia(selectedTaskId.value, pendingFiles, actorName())
    }
    clearPendingMedia(detailPendingMedia)
    showToast('Media updated')
    await refreshAndKeepDetail()
    activeTab.value = 'media'
  } catch (error) {
    showToast(`Attach failed (${error.message})`, true)
  }
}

async function handleDeleteAsset(assetId) {
  if (!selectedTaskId.value) return
  if (!assetId) return
  if (!window.confirm('Delete this media file?')) return
  try {
    await requestJson(`/tasks/${selectedTaskId.value}/assets/${assetId}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'DELETE'
    })
    showToast('Media deleted')
    await refreshAndKeepDetail()
    activeTab.value = 'media'
  } catch (error) {
    showToast(`Delete media failed (${error.message})`, true)
  }
}

async function handleSaveChecklist() {
  if (createMode.value) {
    showToast('Checklist saved in draft. Click Save Content to create task.')
    return
  }
  if (!selectedTaskId.value) return
  try {
    await requestJson(`/tasks/${selectedTaskId.value}/checklist?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'PUT',
      body: { items: parseChecklistLines(checklistText.value) }
    })
    showToast('Checklist saved')
    await refreshAndKeepDetail()
    activeTab.value = 'checklist'
  } catch (error) {
    showToast(`Checklist failed (${error.message})`, true)
  }
}

async function handleAddComment() {
  if (createMode.value) return
  if (!selectedTaskId.value) return
  const content = commentText.value.trim()
  const pendingFiles = commentPendingMedia.value
  if (!content && pendingFiles.length === 0) return
  try {
    let mediaLines = []
    if (pendingFiles.length > 0) {
      const beforeIds = new Set((selectedTask.value?.assets || []).map((asset) => asset.id))
      const updatedTask = await uploadPendingMedia(selectedTaskId.value, pendingFiles, actorName())
      const freshAssets = (updatedTask?.assets || []).filter((asset) => !beforeIds.has(asset.id))
      mediaLines = freshAssets
        .map((asset) => String(asset.url || '').trim())
        .filter(Boolean)
        .map((url) => `${COMMENT_MEDIA_PREFIX}${url}`)
      clearPendingMedia(commentPendingMedia)
    }
    const composed = [content, ...mediaLines].filter(Boolean).join('\n').trim()
    if (!composed) {
      showToast('Nothing to send', true)
      return
    }
    await requestJson(`/tasks/${selectedTaskId.value}/comments`, {
      method: 'POST',
      body: { content: composed, user_name: actorName() }
    })
    commentText.value = ''
    showToast('Comment saved')
    await refreshAndKeepDetail()
    activeTab.value = 'comments'
  } catch (error) {
    showToast(`Comment failed (${error.message})`, true)
  }
}

async function handleDeleteTask() {
  if (createMode.value) return
  if (!selectedTaskId.value) return
  if (!window.confirm('Delete this task? This action cannot be undone.')) return
  try {
    await requestJson(`/tasks/${selectedTaskId.value}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'DELETE'
    })
    showToast('Task deleted')
    closeDetail()
    await loadDashboard()
  } catch (error) {
    showToast(`Delete failed (${error.message})`, true)
  }
}

async function handleRunReminders() {
  try {
    const result = await requestJson('/reminders/run', {
      method: 'POST',
      body: { limit: 200 }
    })
    showToast(`Reminders processed: ${result.processed}`)
  } catch (error) {
    showToast(`Reminder run failed (${error.message})`, true)
  }
}

function onDragStart(taskId) {
  draggingTaskId.value = taskId
}

function onDragEnd() {
  draggingTaskId.value = null
  dragOverStatus.value = ''
}

function onDragEnterColumn(status) {
  if (!draggingTaskId.value) return
  dragOverStatus.value = status
}

function onDragLeaveColumn(status) {
  if (dragOverStatus.value === status) {
    dragOverStatus.value = ''
  }
}

async function onDropToStatus(status) {
  if (!draggingTaskId.value) return
  const taskId = draggingTaskId.value
  draggingTaskId.value = null
  dragOverStatus.value = ''
  await updateTaskStatus(taskId, status)
}

function openFromPath() {
  const path = String(window.location.pathname || '')
  if (/^\/(?:social\/)?dashboard\/campaigns\/?$/.test(path)) {
    activeView.value = 'campaigns'
    return
  }
  if (/^\/(?:social\/)?dashboard\/users\/?$/.test(path)) {
    activeView.value = isAdmin.value ? 'users' : 'overview'
    return
  }
  activeView.value = 'overview'
  const match = path.match(/^\/(?:social\/)?dashboard\/tasks?\/([^/]+)\/?$/)
  if (match) {
    openTask(match[1], false)
  }
}

onMounted(async () => {
  loadTimelinePrefs()

  const rawAuth = localStorage.getItem(AUTH_STORAGE_KEY)
  if (rawAuth) {
    try {
      const parsed = JSON.parse(rawAuth)
      auth.token = parsed.token || ''
      auth.user = parsed.user || null
      syncProfileForm()
    } catch {
      clearAuthState()
    }
  }
  if (auth.token) {
    const stillValid = await refreshMe()
    if (stillValid) {
      await bootstrapAfterAuth()
    }
  }
  window.addEventListener('pointerdown', handlePointerDown)
  window.addEventListener('popstate', openFromPath)
})

watch(
  () => [timelinePrefs.dayWidth, timelinePrefs.cardScale],
  ([dayWidth, cardScale]) => {
    localStorage.setItem(
      TIMELINE_PREFS_KEY,
      JSON.stringify({
        dayWidth: clamp(Number(dayWidth), 140, 320),
        cardScale: clamp(Number(cardScale), 90, 200),
      })
    )
  }
)

watch(
  () => [activeView.value, timeline.value.totalDays, timeline.value.dayWidth],
  ([view, totalDays]) => {
    if (view !== 'overview') return
    if (!Number.isFinite(totalDays) || totalDays <= 0) return
    tryAutoFocusTimeline()
  }
)

watch(
  () => selectedTaskId.value,
  () => {
    previewCarouselIndex.value = 0
  }
)

watch(
  () => previewAssets.value.length,
  (length) => {
    if (length <= 0) {
      previewCarouselIndex.value = 0
      return
    }
    previewCarouselIndex.value = clamp(previewCarouselIndex.value, 0, length - 1)
  }
)

watch(
  () => [activeTab.value, selectedTaskId.value, createMode.value],
  ([tab, taskId, isCreate]) => {
    if (isCreate || !taskId) return
    if (tab === 'preview') {
      loadTaskPreviewLink()
    }
  }
)

onUnmounted(() => {
  window.removeEventListener('pointerdown', handlePointerDown)
  window.removeEventListener('popstate', openFromPath)
  clearPendingMedia(detailPendingMedia)
  clearPendingMedia(commentPendingMedia)
  endTimelinePan()
})
</script>

<template>
  <div>
    <section v-if="!auth.token || !auth.user" class="login-shell">
      <div class="topo-overlay" aria-hidden="true"></div>
      <div class="login-card card-surface">
        <p class="eyebrow">Shared Auth</p>
        <h1>Login</h1>
        <p class="subtle">Use Etsy account or local user credentials.</p>
        <form class="form-grid" @submit.prevent="login">
          <label class="field"><span>Username</span><input v-model="auth.username" type="text" autocomplete="username" /></label>
          <label class="field"><span>Password</span><input v-model="auth.password" type="password" autocomplete="current-password" /></label>
          <div class="field actions-row full">
            <button class="primary-btn" type="submit" :disabled="authLoading">{{ authLoading ? 'Signing in...' : 'Sign In' }}</button>
          </div>
        </form>
      </div>
    </section>

    <template v-else>
    <div class="topo-overlay" aria-hidden="true"></div>
    <main class="dashboard-shell">
      <header class="main-nav card-surface">
        <div class="brand">
          <span class="brand-mark">✶</span>
          <span class="brand-text">Social Tasker</span>
        </div>
        <nav class="menu" aria-label="Main navigation">
          <button class="menu-item" :class="{ active: activeView === 'overview' }" type="button" @click="openOverviewSection()">Overview</button>
          <button class="menu-item" type="button" @click="openOverviewSection('board')">Kanban</button>
          <button class="menu-item" type="button" @click="openOverviewSection('timeline')">Calendar</button>
          <button class="menu-item" type="button" @click="openOverviewSection('analytics')">Analytics</button>
          <button class="menu-item" :class="{ active: activeView === 'campaigns' }" type="button" @click="openCampaignsView()">Campaigns</button>
          <button v-if="isAdmin" class="menu-item" :class="{ active: activeView === 'users' }" type="button" @click="openUsersView()">Users</button>
        </nav>
        <div class="actions">
          <button class="ghost-btn" type="button" @click="openProfileSettings">Settings</button>
          <button class="ghost-btn" type="button" @click="handleRunReminders">Run Reminders</button>
          <button class="ghost-btn" type="button" @click="logout">Logout</button>
          <span class="pill user-pill">
            <img v-if="currentUserAvatar" class="pill-avatar" :src="currentUserAvatar" alt="" />
            {{ auth.user.name || auth.user.username }} ({{ auth.user.role }})
          </span>
        </div>
      </header>

      <template v-if="activeView === 'overview'">
      <section class="hero card-surface">
        <div>
          <p class="eyebrow">Social Content Command Center</p>
          <h1>Overview</h1>
          <p class="subtle">One database, two interfaces, shared truth.</p>
        </div>
        <div class="hero-badges">
          <span v-for="(badge, index) in heroBadges" :key="badge" class="pill" :class="index === 1 ? 'overdue-pill' : ''">
            {{ badge }}
          </span>
        </div>
      </section>

      <section id="analytics" class="stats-grid">
        <article class="metric-card upcoming">
          <h3>Upcoming Tasks</h3>
          <p class="metric">{{ metrics.upcoming }}</p>
          <span class="metric-note overdue-alert">{{ analytics.overdue_count }} overdue in queue</span>
        </article>
        <article class="metric-card in-progress">
          <h3>In-Progress Tasks</h3>
          <p class="metric">{{ metrics.inProgress }}</p>
          <span class="metric-note">{{ analytics.total_this_week }} planned this week</span>
        </article>
        <article class="metric-card completed">
          <h3>Completed Tasks</h3>
          <p class="metric">{{ metrics.completed }}</p>
          <span class="metric-note">{{ analytics.campaign_count }} campaigns active</span>
        </article>
      </section>

      <section class="content-grid">
        <div class="left-column">
          <article id="board" class="card-surface board">
            <div class="board-head">
              <div>
                <h2>Kanban Pulse</h2>
                <span class="subtle">{{ flatTasks.length }} tasks</span>
              </div>
              <div class="board-head-actions">
                <p class="subtle">Drag card across columns to update status. Click card to edit popup.</p>
              </div>
            </div>

            <div class="board-tools">
              <span class="subtle">Visible fields:</span>
              <label><input v-model="visibleFields.type" type="checkbox" /> Type</label>
              <label><input v-model="visibleFields.airDate" type="checkbox" /> Air Date</label>
              <label><input v-model="visibleFields.assignee" type="checkbox" /> Assignee</label>
            </div>

            <div class="kanban-columns">
              <section
                v-for="status in statusOrder"
                :key="status"
                class="kanban-col"
                :class="{ 'drag-over': dragOverStatus === status }"
                :data-status="status"
                @dragover.prevent
                @dragenter.prevent="onDragEnterColumn(status)"
                @dragleave.self="onDragLeaveColumn(status)"
                @drop="onDropToStatus(status)"
              >
                <header>
                  <strong>{{ statusLabels[status] }}</strong>
                  <span class="pill">{{ kanban[status]?.length || 0 }}</span>
                </header>
                <ul class="drop-zone">
                  <li
                    v-if="draggingTaskId && dragOverStatus === status"
                    class="kanban-card drop-preview"
                  >
                    Drop here to move to {{ statusLabels[status] }}
                  </li>
                  <li
                    v-for="task in kanban[status]"
                    :key="task.id"
                    class="kanban-card"
                    :class="typeClass(task.type)"
                    :style="campaignAccentStyle(task)"
                    draggable="true"
                    @dragstart="onDragStart(task.id)"
                    @dragend="onDragEnd"
                    @click="openTask(task.id)"
                  >
                    <div v-if="task.campaign" class="task-campaign-row" :style="{ '--campaign-color': campaignThemeFromTask(task)?.color }">
                      <span class="task-campaign-icon">{{ campaignThemeFromTask(task)?.icon }}</span>
                      <span class="task-campaign-name">{{ task.campaign }}</span>
                    </div>
                    <div class="kanban-title-row">
                      <strong>{{ task.title }}</strong>
                      <span
                        v-if="visibleFields.assignee"
                        class="task-assignee-badge"
                        :title="assigneeDisplay(task.assignee)"
                        :aria-label="`Assignee ${assigneeDisplay(task.assignee)}`"
                      >
                        <img
                          v-if="assigneeAvatarUrl(task.assignee)"
                          class="task-assignee-avatar"
                          :src="assigneeAvatarUrl(task.assignee)"
                          alt=""
                        />
                        <span
                          v-else
                          class="task-assignee-fallback"
                          :style="{ background: assigneeAvatarColor(task.assignee || 'Unassigned') }"
                        >
                          {{ assigneeInitials(task.assignee || 'Unassigned') }}
                        </span>
                      </span>
                    </div>
                    <div class="badges">
                      <span
                        v-for="(badge, idx) in cardBadges(task)"
                        :key="`${task.id}-${idx}`"
                        class="card-badge"
                        :class="badge.className"
                      >
                        {{ badge.text }}
                      </span>
                    </div>
                    <button
                      v-if="normalizeQuickNote(task.quick_note)"
                      type="button"
                      class="kanban-note note-preview-btn"
                      :style="noteCardStyle(task)"
                      :title="normalizeQuickNote(task.quick_note)"
                      @click.stop="openNotePreview(task, 'kanban')"
                    >
                      {{ previewQuickNote(task.quick_note, 78) }}
                    </button>
                    <div class="kanban-checks">
                      <span :class="{ done: task.caption_done }">Caption: {{ task.caption_done ? 'Done' : 'Missing' }}</span>
                      <span :class="{ done: task.hashtag_done }">Hashtag: {{ task.hashtag_done ? 'Done' : 'Missing' }}</span>
                      <span :class="{ done: task.media_done }">Media: {{ task.media_done ? 'Done' : 'Missing' }}</span>
                    </div>
                  </li>
                  <li v-if="(kanban[status] || []).length === 0" class="kanban-card">No tasks yet</li>
                </ul>
                <button class="col-create-btn" type="button" @click="openCreateInColumn(status)">+ Create</button>
              </section>
            </div>
          </article>

          <article id="timeline" class="card-surface roadmap">
            <div class="roadmap-head">
              <div>
                <h2>Project Roadmap</h2>
                <p class="subtle">Drag horizontal to move across the month timeline</p>
              </div>
              <div class="timeline-controls">
                <label>
                  Day Width
                  <input v-model.number="timelinePrefs.dayWidth" type="range" min="140" max="320" step="10" />
                </label>
                <label>
                  Card Size
                  <input v-model.number="timelinePrefs.cardScale" type="range" min="90" max="200" step="5" />
                </label>
              </div>
            </div>
            <div
              ref="timelineViewportRef"
              class="timeline-viewport"
              :class="{ dragging: timelinePanState.active }"
              @mousedown="startTimelinePan"
              @mousemove="moveTimelinePan"
              @mouseup="endTimelinePan"
              @mouseleave="endTimelinePan"
            >
              <div
                class="timeline-wrap"
                :style="{
                  '--timeline-day-width': `${timeline.dayWidth}px`,
                  '--timeline-card-height': `${timeline.cardHeight}px`,
                  '--timeline-media-height': `${timeline.mediaHeight}px`
                }"
              >
                <div
                  class="timeline-axis"
                  :style="{ gridTemplateColumns: `repeat(${timeline.totalDays}, ${timeline.dayWidth}px)`, width: `${timeline.gridWidth}px` }"
                >
                  <template v-if="timeline.days.length === 0">
                    <span style="grid-column: 1 / -1">No schedule yet</span>
                  </template>
                  <span v-for="day in timeline.days" :key="day.key">
                    <small>{{ day.weekday }}</small>
                    <strong>{{ day.monthDay }}</strong>
                  </span>
                </div>
                <div
                  class="timeline-lanes"
                  :style="{
                    minHeight: `${Math.max(420, timeline.laneTopOffset + timeline.laneCount * timeline.rowHeight + 20)}px`,
                    width: `${timeline.gridWidth}px`,
                    backgroundSize: `${timeline.dayWidth}px 100%`
                  }"
                >
                  <div
                    class="timeline-create-overlay"
                    :style="{
                      gridTemplateColumns: `repeat(${timeline.totalDays}, ${timeline.dayWidth}px)`,
                      width: `${timeline.gridWidth}px`,
                      height: `${timeline.createRowHeight}px`
                    }"
                  >
                    <div v-for="day in timeline.days" :key="`create-${day.key}`" class="timeline-create-overlay-cell">
                      <button class="timeline-create-btn" type="button" @click.stop="openCreateForTimelineDay(day.iso)">+ Create</button>
                    </div>
                  </div>
                  <div
                    v-for="campaign in timeline.campaignBars"
                    :key="`camp-${campaign.id}`"
                    class="timeline-campaign-bar"
                    :class="`status-${campaign.status}`"
                    :style="campaign.style"
                  >
                    <span class="campaign-icon">{{ campaign.icon }}</span>
                    <span class="campaign-name">{{ campaign.name }}</span>
                  </div>
                  <template v-if="timeline.cards.length === 0 && timeline.campaignBars.length === 0">
                    <p style="padding:16px">Set air_date to render roadmap bars.</p>
                  </template>
                  <div
                    v-for="task in timeline.cards"
                    :key="task.id"
                    class="timeline-item timeline-tile"
                    :class="task.status"
                    :style="[task.style, campaignAccentStyle(task)]"
                    role="button"
                    tabindex="0"
                    @click="openTask(task.id)"
                    @keydown.enter.prevent="openTask(task.id)"
                    @keydown.space.prevent="openTask(task.id)"
                  >
                    <div class="timeline-tile-head">
                      <div class="timeline-head-left">
                        <span class="timeline-platform">IG</span>
                        <span
                          class="task-assignee-badge task-assignee-badge-sm"
                          :title="assigneeDisplay(task.assignee)"
                          :aria-label="`Assignee ${assigneeDisplay(task.assignee)}`"
                        >
                          <img
                            v-if="assigneeAvatarUrl(task.assignee)"
                            class="task-assignee-avatar"
                            :src="assigneeAvatarUrl(task.assignee)"
                            alt=""
                          />
                          <span
                            v-else
                            class="task-assignee-fallback"
                            :style="{ background: assigneeAvatarColor(task.assignee || 'Unassigned') }"
                          >
                            {{ assigneeInitials(task.assignee || 'Unassigned') }}
                          </span>
                        </span>
                      </div>
                      <div class="timeline-head-right">
                        <span class="timeline-type-chip" :class="typeClass(task.type)">
                          {{ String(task.type || '').toUpperCase() || 'POST' }}
                        </span>
                      </div>
                    </div>
                    <div class="timeline-media-frame" :class="typeClass(task.type)">
                      <img
                        v-if="isTimelineThumbVisible(task.media_thumbnail)"
                        class="timeline-media-img"
                        :src="task.media_thumbnail"
                        alt=""
                        @error="markTimelineThumbFailed(task.media_thumbnail)"
                      />
                      <button
                        v-else-if="normalizeQuickNote(task.quick_note)"
                        type="button"
                        class="timeline-no-media note-preview-btn"
                        :style="noteCardStyle(task)"
                        :title="normalizeQuickNote(task.quick_note)"
                        @click.stop="openNotePreview(task, 'timeline')"
                      >
                        {{ previewQuickNote(task.quick_note, 118) }}
                      </button>
                      <div v-else class="timeline-no-media" :style="noteCardStyle(task)">No media yet</div>
                      <div v-if="task.type === 'story' && isTimelineThumbVisible(task.media_thumbnail)" class="timeline-story-overlay">
                        <span class="timeline-story-icon">+</span>
                      </div>
                    </div>
                    <button
                      v-if="task.type !== 'story' && isTimelineThumbVisible(task.media_thumbnail) && normalizeQuickNote(task.quick_note)"
                      type="button"
                      class="timeline-content-snippet note-preview-btn"
                      :style="noteCardStyle(task)"
                      :title="normalizeQuickNote(task.quick_note)"
                      @click.stop="openNotePreview(task, 'timeline')"
                    >
                      {{ previewQuickNote(task.quick_note, 76) }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </article>
        </div>

        <aside class="right-column">
          <article class="card-surface panel">
            <div class="panel-head">
              <h2>Recent Messages</h2>
              <button class="link-btn" type="button">View all</button>
            </div>
            <ul class="panel-list">
              <li v-for="task in sortedMessages" :key="task.id" class="message">
                <span class="avatar">{{ initials(task.assignee || task.campaign || 'SO') }}</span>
                <div>
                  <h4>{{ task.assignee || 'Content Team' }}</h4>
                  <p>{{ task.title }}</p>
                  <p v-if="task.missing_count > 0">{{ task.missing_count }} field(s) missing before auto package.</p>
                  <p v-else-if="task.status === 'posted'">Marked posted by team.</p>
                  <p v-else>Waiting next status update.</p>
                </div>
              </li>
            </ul>
          </article>

          <article class="card-surface panel">
            <div class="panel-head">
              <h2>Today's Tasks</h2>
              <span class="pill">{{ todayItems.length }}</span>
            </div>
            <ul class="task-list">
              <li v-for="task in todayItems" :key="task.id" class="today-item">
                <span class="avatar">{{ initials(task.assignee || 'NA') }}</span>
                <div>
                  <h4>{{ task.title }}</h4>
                  <p>{{ fmtDate(task.air_date, true) }} · {{ statusLabels[task.status] || task.status }}</p>
                </div>
                <button
                  class="tiny-btn quick-status"
                  type="button"
                  @click="updateTaskStatus(task.id, task.status === 'posted' ? 'ready' : 'posted')"
                >
                  {{ task.status === 'posted' ? 'Mark Ready' : 'Mark Posted' }}
                </button>
              </li>
              <li v-if="todayItems.length === 0" class="today-item">
                <div>
                  <h4>No tasks today</h4>
                  <p>Air-date tasks for today will show here.</p>
                </div>
              </li>
            </ul>
          </article>
        </aside>
      </section>
      </template>

      <section v-else-if="activeView === 'campaigns'" class="campaigns-page card-surface">
        <div class="campaigns-head">
          <div>
            <p class="eyebrow">Workspace</p>
            <h1>Campaigns</h1>
            <p class="subtle">Manage campaign info and reuse it from task forms.</p>
          </div>
          <button class="primary-btn" type="button" @click="openCampaignCreate">Create Campaign</button>
        </div>
        <div class="campaign-grid">
          <button class="campaign-create-card" type="button" @click="openCampaignCreate">
            <span>+</span>
            <strong>Create campaign</strong>
          </button>
          <article
            v-for="campaign in campaigns"
            :key="campaign.id"
            class="campaign-card"
            :style="{ '--campaign-color': sanitizeCampaignColor(campaign.color, DEFAULT_CAMPAIGN_COLOR) }"
          >
            <header class="campaign-card-head">
              <div>
                <h3><span class="campaign-title-icon">{{ normalizeCampaignIcon(campaign.icon, DEFAULT_CAMPAIGN_ICON) }}</span>{{ campaign.name }}</h3>
                <p class="subtle">{{ campaignDateRange(campaign) }}</p>
              </div>
              <span class="pill">{{ campaign.status || 'planning' }}</span>
            </header>
            <p class="campaign-card-description">{{ campaign.description || 'No description yet.' }}</p>
            <div class="campaign-card-meta">
              <span class="pill">{{ campaign.requires_product_url ? 'Product URL required' : 'Branding optional URL' }}</span>
            </div>
            <div class="campaign-card-actions">
              <button class="ghost-btn" type="button" @click="openCampaignEdit(campaign)">Edit</button>
              <button class="ghost-btn danger-btn" type="button" @click="removeCampaign(campaign.id)">Delete</button>
            </div>
          </article>
        </div>
      </section>

      <section v-else-if="activeView === 'users' && isAdmin" class="campaigns-page card-surface">
        <div class="campaigns-head">
          <div>
            <p class="eyebrow">Admin</p>
            <h1>User Management</h1>
            <p class="subtle">Create users, set role, avatar and reset password for assignment.</p>
          </div>
        </div>
        <form class="form-grid user-create-form" @submit.prevent="createManagedUser">
          <label class="field"><span>Full name</span><input v-model="userEditor.name" type="text" /></label>
          <label class="field"><span>Username</span><input v-model="userEditor.username" type="text" /></label>
          <label class="field"><span>Role</span><input v-model="userEditor.role" type="text" placeholder="content / designer / admin" /></label>
          <label class="field"><span>Zalo ID</span><input v-model="userEditor.zalo_user_id" type="text" placeholder="optional" /></label>
          <label class="field"><span>Password</span><input v-model="userEditor.password" type="password" /></label>
          <label class="field full"><span>Avatar file (optional)</span><input type="file" accept="image/*" @change="onNewUserAvatarChange" /></label>
          <div class="field actions-row full"><button class="primary-btn save-btn" type="submit">Add User</button></div>
        </form>

        <div class="list-shell">
          <article v-for="row in userRows" :key="row.id" class="list-item user-row">
            <img v-if="row.avatar_url" :src="row.avatar_url" alt="" class="avatar-preview" />
            <div v-else class="avatar-preview avatar-preview-fallback">{{ (row.name || row.username || '?').slice(0, 1).toUpperCase() }}</div>
            <div class="user-row-main">
              <div class="user-row-grid">
                <label class="field"><span>Name</span><input v-model="row.name" type="text" /></label>
                <label class="field"><span>Username</span><input v-model="row.username" type="text" /></label>
                <label class="field"><span>Role</span><input v-model="row.role" type="text" /></label>
                <label class="field"><span>Zalo ID</span><input v-model="row.zalo_user_id" type="text" /></label>
                <label class="field"><span>Avatar file</span><input type="file" accept="image/*" @change="onManagedUserAvatarChange(row.id, $event)" /></label>
                <label class="field checkbox-field">
                  <input v-model="row.is_active" type="checkbox" />
                  <span>Active</span>
                </label>
                <label class="field">
                  <span>Set password</span>
                  <input v-model="row.temp_password" type="password" placeholder="new password" />
                </label>
              </div>
              <div class="user-row-actions">
                <button class="ghost-btn" type="button" @click="uploadManagedUserAvatar(row)">Upload Avatar</button>
                <button class="ghost-btn save-btn" type="button" @click="saveManagedUser(row)">Save</button>
                <button class="ghost-btn" type="button" @click="saveManagedUserPassword(row)">Set Password</button>
                <button class="ghost-btn danger-btn" type="button" @click="removeManagedUser(row)">Delete</button>
              </div>
            </div>
          </article>
          <article v-if="!usersLoading && userRows.length === 0" class="list-item">
            <p class="meta">No users yet.</p>
          </article>
        </div>
      </section>
    </main>

    <section v-if="detailOpen" class="detail card-surface open">
      <div class="detail-head">
        <h2>{{ createMode ? 'Create Task' : selectedTask?.title }}</h2>
        <div class="detail-head-actions">
          <button
            class="ghost-btn close-x-btn"
            type="button"
            aria-label="Close Task Popup"
            title="Close"
            @click="closeDetail"
          >
            X
          </button>
        </div>
      </div>

      <div class="detail-topline">
        <label class="status-combo">
          <span>Status</span>
          <select id="statusSelect" :class="statusClass(statusValue)" v-model="statusValue" @change="handleStatusSelectChange">
            <option v-for="status in statusOrder" :key="status" :value="status">{{ statusLabels[status] }}</option>
          </select>
        </label>
        <label v-if="createMode" class="status-combo">
          <span>Type</span>
          <select id="createTypeSelect" v-model="createType">
            <option value="story">Story</option>
            <option value="reel">Reel</option>
            <option value="post">Post</option>
          </select>
        </label>
      </div>

      <div class="detail-tabs">
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'content' }" @click="activeTab = 'content'">Content</button>
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'media' }" @click="activeTab = 'media'">Media</button>
        <button v-if="!createMode" type="button" class="tab-btn" :class="{ active: activeTab === 'comments' }" @click="activeTab = 'comments'">Comments</button>
        <button v-if="!createMode" type="button" class="tab-btn" :class="{ active: activeTab === 'activity' }" @click="activeTab = 'activity'">History</button>
        <button v-if="!createMode" type="button" class="tab-btn" :class="{ active: activeTab === 'preview' }" @click="activeTab = 'preview'">Preview</button>
      </div>

      <div v-show="activeTab === 'content'" class="tab-panel active">
        <form class="form-grid" @submit.prevent="handleSaveContent">
          <label class="field full"><span>Title</span><input v-model="contentForm.title" type="text" /></label>
          <label class="field full">
            <span>Quick Note (for board/timeline, max {{ QUICK_NOTE_MAX_LENGTH }})</span>
            <textarea
              v-model="contentForm.quick_note"
              rows="3"
              :maxlength="QUICK_NOTE_MAX_LENGTH"
              placeholder="Write short context for the card"
            ></textarea>
            <small class="field-counter">{{ (contentForm.quick_note || '').length }}/{{ QUICK_NOTE_MAX_LENGTH }}</small>
          </label>
          <label class="field full">
            <span>Note color</span>
            <div class="note-color-control-row">
              <input
                class="note-color-input"
                type="color"
                :value="contentForm.note_color"
                @change="setContentNoteColor($event.target.value)"
              />
              <div class="note-color-preset-row">
                <button
                  v-for="color in NOTE_COLOR_PRESETS"
                  :key="`task-note-${selectedTask?.id || 'new'}-${color}`"
                  class="note-color-preset"
                  type="button"
                  :style="{ background: color }"
                  :class="{ active: sanitizeHexColor(contentForm.note_color, DEFAULT_NOTE_COLOR) === color }"
                  @click="setContentNoteColor(color)"
                >
                  <span v-if="sanitizeHexColor(contentForm.note_color, DEFAULT_NOTE_COLOR) === color">✓</span>
                </button>
              </div>
            </div>
          </label>
          <label class="field full"><span>Caption</span><textarea v-model="contentForm.caption" rows="7"></textarea></label>
          <label class="field"><span>Hashtags (space separated)</span><input v-model="contentForm.hashtags" type="text" /></label>
          <label class="field"><span>Mentions (space separated)</span><input v-model="contentForm.mentions" type="text" /></label>
          <label class="field">
            <span>Assignee Name</span>
            <div ref="assigneePickerRef" class="assignee-picker">
              <button
                class="assignee-picker-trigger"
                type="button"
                :aria-expanded="assigneePickerOpen"
                @click="toggleAssigneePicker"
              >
                <span class="task-assignee-badge">
                  <img
                    v-if="selectedAssigneeUser?.avatar_url"
                    class="task-assignee-avatar"
                    :src="selectedAssigneeUser.avatar_url"
                    alt=""
                  />
                  <span
                    v-else
                    class="task-assignee-fallback"
                    :style="{ background: assigneeAvatarColor(contentForm.assignee_name || 'Unassigned') }"
                  >
                    {{ assigneeInitials(contentForm.assignee_name || 'Unassigned') }}
                  </span>
                </span>
                <span class="assignee-picker-label">{{ assigneeDisplay(contentForm.assignee_name) }}</span>
                <span class="assignee-picker-caret">{{ assigneePickerOpen ? '▴' : '▾' }}</span>
              </button>
              <div v-if="assigneePickerOpen" class="assignee-picker-menu">
                <button
                  class="assignee-picker-option assignee-picker-option-unassigned"
                  :class="{ active: !contentForm.assignee_name }"
                  type="button"
                  @click="chooseAssignee('')"
                >
                  <span class="task-assignee-fallback" :style="{ background: '#8e8a7f' }">U</span>
                  <span class="assignee-picker-name">Unassigned</span>
                </button>
                <button
                  v-if="auth.user?.name || auth.user?.username"
                  class="assignee-picker-option"
                  type="button"
                  @click="assignToMe"
                >
                  <img
                    v-if="auth.user?.avatar_url"
                    class="task-assignee-avatar"
                    :src="auth.user.avatar_url"
                    alt=""
                  />
                  <span
                    v-else
                    class="task-assignee-fallback"
                    :style="{ background: assigneeAvatarColor(auth.user?.name || auth.user?.username || 'Me') }"
                  >
                    {{ assigneeInitials(auth.user?.name || auth.user?.username || 'Me') }}
                  </span>
                  <span class="assignee-picker-name">
                    {{ auth.user?.name || auth.user?.username }} (Assign to me)
                  </span>
                </button>
                <button
                  v-for="user in assigneeUsers"
                  :key="user.id"
                  class="assignee-picker-option"
                  :class="{ active: nameKey(contentForm.assignee_name) === nameKey(user.name) }"
                  type="button"
                  @click="chooseAssignee(user.name)"
                >
                  <img v-if="user.avatar_url" class="task-assignee-avatar" :src="user.avatar_url" alt="" />
                  <span v-else class="task-assignee-fallback" :style="{ background: assigneeAvatarColor(user.name) }">
                    {{ assigneeInitials(user.name) }}
                  </span>
                  <span class="assignee-picker-name">{{ user.name }}</span>
                </button>
              </div>
            </div>
          </label>
          <label class="field">
            <span>Campaign Name</span>
            <select v-model="contentForm.campaign_name">
              <option value="">No campaign</option>
              <option v-for="campaign in campaignOptions" :key="campaign.id" :value="campaign.name">
                {{ normalizeCampaignIcon(campaign.icon, DEFAULT_CAMPAIGN_ICON) }} {{ campaign.name }}
              </option>
            </select>
          </label>
          <label class="field"><span>Air Date</span><input v-model="contentForm.air_date" type="datetime-local" /></label>
          <div class="field actions-row"><button class="primary-btn" :class="{ 'save-btn': !createMode }" type="submit">{{ createMode ? 'Create Task' : 'Save Content' }}</button></div>
        </form>
      </div>

      <div v-show="activeTab === 'media'" class="tab-panel active">
        <form class="form-grid" @submit.prevent="handleAttachMedia">
          <label class="field full">
            <span>Quick upload (drag/drop/paste or choose files)</span>
            <div
              class="media-dropzone"
              tabindex="0"
              @dragover.prevent
              @drop.prevent="onDetailMediaDrop"
              @paste.prevent="onDetailMediaPaste"
            >
              Drop or paste files here
            </div>
            <input type="file" multiple accept="image/*,video/*" @change="onDetailMediaFilesChange" />
          </label>
          <div class="field full upload-preview-list">
            <article v-for="item in detailPendingMedia" :key="item.id" class="upload-preview-item">
              <img v-if="item.kind === 'image'" :src="item.preview_url" alt="" class="upload-preview-thumb" />
              <video v-else :src="item.preview_url" class="upload-preview-thumb" muted playsinline></video>
              <div>
                <strong>{{ item.file.name }}</strong>
                <p class="meta">{{ Math.ceil(item.file.size / 1024) }} KB</p>
              </div>
              <button class="ghost-btn" type="button" @click="removePendingMedia(detailPendingMedia, item.id)">Remove</button>
            </article>
            <article v-if="detailPendingMedia.length === 0" class="upload-preview-item empty">
              <p class="meta">No pending files.</p>
            </article>
          </div>
          <div class="field actions-row full centered-attach-row">
            <button class="primary-btn attach-media-btn" type="submit">Attach Media</button>
          </div>
        </form>
        <div v-if="!createMode" class="list-shell">
          <div v-if="selectedTaskAssets.length > 0" class="attachments-table">
            <header class="attachments-head">
              <strong>Attachments</strong>
              <span class="meta">{{ selectedTaskAssets.length }} item(s)</span>
            </header>
            <div class="attachments-grid-head">
              <span>Name</span>
              <span>Type</span>
              <span>Date added</span>
              <span>Actions</span>
            </div>
            <article v-for="asset in selectedTaskAssets" :key="asset.id" class="attachments-row">
              <div class="attachments-name">
                <img v-if="asset.kind === 'image'" :src="asset.url" alt="" class="attachments-thumb" />
                <video v-else :src="asset.url" class="attachments-thumb" muted preload="metadata"></video>
                <span class="attachments-file" :title="assetFileName(asset.url)">{{ assetFileName(asset.url) }}</span>
              </div>
              <span class="attachments-type">{{ String(asset.kind || '').toUpperCase() }}</span>
              <span class="attachments-date">{{ fmtDate(asset.created_at) }}</span>
              <span class="attachments-actions">
                <a class="tiny-btn" :href="asset.url" target="_blank" rel="noopener noreferrer">View</a>
                <a class="tiny-btn" :href="asset.url" :download="assetFileName(asset.url)">Save</a>
                <button class="tiny-btn danger-btn media-delete-btn" type="button" @click="handleDeleteAsset(asset.id)">Delete</button>
              </span>
            </article>
          </div>
          <article v-else class="list-item">
            <p class="meta">No real media attached yet. Upload files to see preview.</p>
          </article>
        </div>
      </div>

      <div v-if="!createMode" v-show="activeTab === 'comments'" class="tab-panel active">
        <form class="inline-form" @submit.prevent="handleAddComment">
          <input v-model="commentText" type="text" placeholder="Write comment..." />
          <button class="primary-btn" type="submit">{{ commentPendingMedia.length > 0 ? 'Send + Attach' : 'Send' }}</button>
        </form>
        <div class="comment-media-tools">
          <input type="file" multiple accept="image/*,video/*" @change="onCommentMediaFilesChange" />
          <button
            v-if="commentPendingMedia.length > 0"
            class="ghost-btn"
            type="button"
            @click="clearPendingMedia(commentPendingMedia)"
          >
            Clear pending
          </button>
        </div>
        <div v-if="commentPendingMedia.length > 0" class="upload-preview-list comment-upload-preview">
          <article v-for="item in commentPendingMedia" :key="item.id" class="upload-preview-item">
            <img v-if="item.kind === 'image'" :src="item.preview_url" alt="" class="upload-preview-thumb" />
            <video v-else :src="item.preview_url" class="upload-preview-thumb" muted playsinline></video>
            <div>
              <strong>{{ item.file.name }}</strong>
              <p class="meta">{{ Math.ceil(item.file.size / 1024) }} KB</p>
            </div>
            <button class="ghost-btn" type="button" @click="removePendingMedia(commentPendingMedia, item.id)">Remove</button>
          </article>
        </div>
        <div class="list-shell">
          <article
            v-for="comment in (selectedTask?.comments || []).slice().sort((a,b)=>new Date(a.created_at)-new Date(b.created_at))"
            :key="comment.id"
            class="list-item comment-item"
          >
            <div class="comment-head">
              <span class="task-assignee-badge comment-avatar">
                <img v-if="commentAuthorAvatar(comment)" class="task-assignee-avatar" :src="commentAuthorAvatar(comment)" alt="" />
                <span
                  v-else
                  class="task-assignee-fallback"
                  :style="{ background: assigneeAvatarColor(commentAuthorName(comment)) }"
                >
                  {{ assigneeInitials(commentAuthorName(comment)) }}
                </span>
              </span>
              <strong>{{ commentAuthorName(comment) }}</strong>
            </div>
            <p v-if="commentDisplayText(comment)" class="comment-text">{{ commentDisplayText(comment) }}</p>
            <div v-if="commentMediaUrls(comment).length > 0" class="comment-media-grid">
              <a
                v-for="url in commentMediaUrls(comment)"
                :key="`${comment.id}-${url}`"
                class="comment-media-item"
                :href="url"
                target="_blank"
                rel="noopener noreferrer"
              >
                <img v-if="isLikelyImage(url)" :src="url" alt="" class="comment-media-thumb" />
                <video v-else :src="url" class="comment-media-thumb" muted playsinline preload="metadata"></video>
              </a>
            </div>
            <p class="meta">{{ fmtDate(comment.created_at) }}</p>
          </article>
        </div>
      </div>

      <div v-if="!createMode" v-show="activeTab === 'preview'" class="tab-panel active">
        <div class="preview-toolbar">
          <div class="preview-device-switch">
            <button class="switch" :class="{ active: previewDevice === 'desktop' }" type="button" @click="previewDevice = 'desktop'">Desktop</button>
            <button class="switch" :class="{ active: previewDevice === 'mobile' }" type="button" @click="previewDevice = 'mobile'">Mobile</button>
          </div>
          <div class="preview-actions">
            <button class="ghost-btn" type="button" @click="copyPreviewPackage">Copy Content</button>
            <button class="ghost-btn" type="button" @click="downloadCurrentPreviewMedia" :disabled="!previewCurrentAsset">Download current</button>
            <button class="ghost-btn" type="button" @click="downloadAllPreviewMedia" :disabled="previewAssets.length === 0">Download all</button>
            <button class="ghost-btn" type="button" :disabled="previewLinkState.generating" @click="regenerateTaskPreviewLinkAction">
              {{ previewLinkState.generating ? 'Generating...' : (previewLinkState.data?.is_active ? 'Regenerate Link' : 'Generate Link') }}
            </button>
            <button class="ghost-btn" type="button" :disabled="!previewPublicUrl" @click="openPreviewPublicLink">Open Public Link</button>
          </div>
        </div>

        <p class="meta preview-link-meta">
          <template v-if="previewLinkState.loading">Loading preview link...</template>
          <template v-else-if="previewLinkState.data?.is_active && previewPublicUrl">
            Active link: <a :href="previewPublicUrl" target="_blank" rel="noopener noreferrer">{{ previewPublicUrl }}</a>
            · expires {{ fmtDate(previewLinkState.data.expires_at) }}
          </template>
          <template v-else>No active public preview link.</template>
        </p>

        <div class="ig-preview-shell" :class="[`device-${previewDevice}`, `type-${selectedTask?.type || 'post'}`]">
          <header class="ig-preview-head">
            <div class="ig-preview-user">
              <span class="timeline-platform">IG</span>
              <strong>{{ selectedTask?.assignee_name || selectedTask?.assignee || 'Content Team' }}</strong>
            </div>
            <span class="ig-preview-type">{{ String(selectedTask?.type || '').toUpperCase() || 'POST' }}</span>
          </header>

          <div class="ig-preview-media-wrap" :class="{ story: selectedTask?.type === 'story' }">
            <template v-if="previewCurrentAsset">
              <img
                v-if="previewMediaKind(previewCurrentAsset) === 'image'"
                class="ig-preview-media"
                :src="previewCurrentAsset.url"
                alt=""
              />
              <video
                v-else
                class="ig-preview-media"
                :src="previewCurrentAsset.url"
                controls
                playsinline
              ></video>
            </template>
            <template v-else>
              <div class="ig-preview-no-media">
                {{ previewQuickNoteText || 'No media yet' }}
              </div>
            </template>
          </div>

          <div v-if="previewAssets.length > 1" class="ig-preview-carousel-controls">
            <button class="ghost-btn" type="button" @click="previewPrevMedia">Prev</button>
            <span>{{ previewMediaLabel() }}</span>
            <button class="ghost-btn" type="button" @click="previewNextMedia">Next</button>
          </div>

          <div class="ig-preview-fields">
            <article v-for="field in previewFieldCards" :key="field.key" class="ig-preview-field">
              <header class="ig-preview-field-head">
                <span class="ig-preview-field-label">{{ field.label }}</span>
                <button
                  class="ig-preview-copy-btn"
                  type="button"
                  :disabled="!String(field.value || '').trim()"
                  @click="copyPreviewField(field.value, field.label)"
                >
                  ⧉
                </button>
              </header>
              <p class="ig-preview-field-value" :class="{ empty: !String(field.value || '').trim() }">
                {{ String(field.value || '').trim() || field.emptyLabel }}
              </p>
            </article>
          </div>
        </div>
      </div>

      <div v-if="!createMode" v-show="activeTab === 'activity'" class="tab-panel active">
        <div class="list-shell">
          <article v-for="log in (selectedTask?.activity_logs || []).slice().sort((a,b)=>new Date(b.created_at)-new Date(a.created_at))" :key="log.id" class="list-item">
            <strong>{{ log.action }}{{ log.field_name ? ` (${log.field_name})` : '' }}</strong>
            <p>
              {{ [log.old_value ? `from: ${log.old_value}` : '', log.new_value ? `to: ${log.new_value}` : ''].filter(Boolean).join(' · ') || '-' }}
            </p>
            <p class="meta">{{ fmtDate(log.created_at) }}</p>
          </article>
        </div>
      </div>
      <div v-if="!createMode" class="detail-footer-actions">
        <button class="ghost-btn danger-btn" type="button" @click="handleDeleteTask">Delete</button>
      </div>
    </section>

    <div class="modal-backdrop" :class="{ open: notePreview.open }" :aria-hidden="notePreview.open ? 'false' : 'true'" @click="closeNotePreview">
      <section class="modal-card note-preview-card" role="dialog" aria-modal="true" aria-labelledby="notePreviewTitle" @click.stop>
        <header class="modal-head">
          <h3 id="notePreviewTitle">Quick Note</h3>
          <button class="ghost-btn close-x-btn" type="button" aria-label="Close" title="Close" @click="closeNotePreview">X</button>
        </header>
        <p class="meta note-preview-meta">
          {{ notePreview.title }} · {{ notePreview.airDate ? fmtDate(notePreview.airDate) : 'No air date' }}
        </p>
        <textarea
          v-model="notePreview.draft"
          class="note-preview-input"
          :style="{ '--note-bg': notePreview.color }"
          :maxlength="QUICK_NOTE_MAX_LENGTH"
          rows="6"
          placeholder="Write quick note..."
        ></textarea>
        <p class="meta note-preview-meta note-preview-counter">{{ (notePreview.draft || '').length }}/{{ QUICK_NOTE_MAX_LENGTH }}</p>
        <div v-if="notePreview.taskId" class="note-color-control-row note-color-control-row-modal">
          <span class="note-color-control-label">Note color</span>
          <input
            class="note-color-input"
            type="color"
            :value="notePreview.color"
            @change="setNotePreviewColor($event.target.value)"
          />
          <div class="note-color-preset-row">
            <button
              v-for="color in NOTE_COLOR_PRESETS"
              :key="`preview-note-${notePreview.taskId}-${color}`"
              class="note-color-preset"
              type="button"
              :style="{ background: color }"
              :class="{ active: sanitizeHexColor(notePreview.color, DEFAULT_NOTE_COLOR) === color }"
              @click="setNotePreviewColor(color)"
            >
              <span v-if="sanitizeHexColor(notePreview.color, DEFAULT_NOTE_COLOR) === color">✓</span>
            </button>
          </div>
        </div>
        <div class="note-preview-actions">
          <button class="primary-btn save-btn" type="button" :disabled="notePreview.saving" @click="saveNoteFromPreview">
            {{ notePreview.saving ? 'Saving...' : 'Save Note' }}
          </button>
          <button
            v-if="notePreview.taskId"
            class="primary-btn"
            type="button"
            @click="openTaskFromNotePreview"
          >
            Open Full Task
          </button>
        </div>
      </section>
    </div>

    <div class="modal-backdrop" :class="{ open: campaignEditor.open }" :aria-hidden="campaignEditor.open ? 'false' : 'true'" @click="closeCampaignEditor">
      <section class="modal-card settings-card" role="dialog" aria-modal="true" aria-labelledby="campaignEditorTitle" @click.stop>
        <header class="modal-head">
          <h3 id="campaignEditorTitle">{{ campaignEditor.editingId ? 'Edit campaign' : 'Create campaign' }}</h3>
          <button class="ghost-btn close-x-btn" type="button" aria-label="Close" title="Close" @click="closeCampaignEditor">X</button>
        </header>
        <form class="form-grid" @submit.prevent="saveCampaign">
          <label class="field full"><span>Campaign name</span><input v-model="campaignEditor.name" type="text" required /></label>
          <label class="field">
            <span>Status</span>
            <select v-model="campaignEditor.status">
              <option v-for="status in campaignStatusOptions" :key="status" :value="status">{{ status }}</option>
            </select>
          </label>
          <label class="field">
            <span>Campaign color</span>
            <input v-model="campaignEditor.color" type="color" />
            <div class="campaign-color-preset-row">
              <button
                v-for="color in CAMPAIGN_COLOR_PRESETS"
                :key="`campaign-color-${color}`"
                class="campaign-color-preset"
                type="button"
                :style="{ background: color }"
                :class="{ active: sanitizeCampaignColor(campaignEditor.color) === color }"
                @click="campaignEditor.color = color"
              >
                <span v-if="sanitizeCampaignColor(campaignEditor.color) === color">✓</span>
              </button>
            </div>
          </label>
          <label class="field">
            <span>Campaign icon</span>
            <input v-model="campaignEditor.icon" type="text" maxlength="16" />
            <div class="campaign-icon-preset-row">
              <button
                v-for="icon in CAMPAIGN_ICON_PRESETS"
                :key="`campaign-icon-${icon}`"
                class="campaign-icon-preset"
                type="button"
                :class="{ active: normalizeCampaignIcon(campaignEditor.icon) === icon }"
                @click="campaignEditor.icon = icon"
              >
                {{ icon }}
              </button>
            </div>
          </label>
          <label class="field"><span>Start date</span><input v-model="campaignEditor.start_date" type="date" /></label>
          <label class="field"><span>End date</span><input v-model="campaignEditor.end_date" type="date" /></label>
          <label class="field"><span>Link</span><input v-model="campaignEditor.link_url" type="url" placeholder="https://..." /></label>
          <label class="field"><span>Brand</span><input v-model="campaignEditor.brand" type="text" /></label>
          <label class="field"><span>Platform</span><input v-model="campaignEditor.platform" type="text" /></label>
          <label class="field checkbox-field">
            <input v-model="campaignEditor.requires_product_url" type="checkbox" />
            <span>Require Product URL for tasks in this campaign</span>
          </label>
          <label class="field full"><span>Description</span><textarea v-model="campaignEditor.description" rows="6"></textarea></label>
          <div class="field actions-row full">
            <button class="primary-btn" :class="{ 'save-btn': Boolean(campaignEditor.editingId) }" type="submit" :disabled="campaignEditor.saving">
              {{ campaignEditor.saving ? 'Saving...' : (campaignEditor.editingId ? 'Save campaign' : 'Create campaign') }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <div class="modal-backdrop" :class="{ open: settingsOpen }" :aria-hidden="settingsOpen ? 'false' : 'true'">
      <section class="modal-card settings-card" role="dialog" aria-modal="true" aria-labelledby="settingsTitle" @click.stop>
        <header class="modal-head">
          <h3 id="settingsTitle">Profile Settings</h3>
          <button class="ghost-btn close-x-btn" type="button" aria-label="Close" title="Close" @click="settingsOpen = false">X</button>
        </header>

        <form class="form-grid" @submit.prevent="saveProfile">
          <div class="field full">
            <span>Avatar</span>
            <div class="profile-avatar-line">
              <img v-if="profileForm.avatar_url" :src="profileForm.avatar_url" alt="" class="avatar-preview" />
              <div v-else class="avatar-preview avatar-preview-fallback">{{ (profileForm.name || profileForm.username || '?').slice(0, 1).toUpperCase() }}</div>
              <input type="file" accept="image/*" @change="onProfileAvatarChange" />
              <button class="ghost-btn" type="button" :disabled="profileSaving" @click="uploadProfileAvatar">
                {{ profileSaving ? 'Uploading...' : 'Upload Avatar' }}
              </button>
            </div>
          </div>
          <label class="field"><span>Full name</span><input v-model="profileForm.name" type="text" /></label>
          <label class="field"><span>Username</span><input v-model="profileForm.username" type="text" /></label>
          <label class="field"><span>Zalo ID</span><input v-model="profileForm.zalo_user_id" type="text" placeholder="zalo user id" /></label>
          <div class="field actions-row full">
            <button class="primary-btn save-btn" type="submit" :disabled="profileSaving">
              {{ profileSaving ? 'Saving...' : 'Save Profile' }}
            </button>
          </div>
        </form>

        <template v-if="isAdmin">
          <div class="settings-divider"></div>
          <form class="form-grid" @submit.prevent="saveZaloSettings">
            <label class="field full">
              <span>Social group chat ID</span>
              <input
                v-model="zaloSettingsForm.social_group_chat_id"
                type="text"
                placeholder="Zalo group chat id"
              />
              <small class="meta">Source: {{ zaloSettingsForm.source }}</small>
            </label>
            <div class="field actions-row full">
              <button class="primary-btn save-btn" type="submit" :disabled="zaloSettingsSaving">
                {{ zaloSettingsSaving ? 'Saving...' : 'Save Zalo Settings' }}
              </button>
              <button class="ghost-btn" type="button" :disabled="zaloTestSending || zaloSettingsSaving" @click="testZaloSettings">
                {{ zaloTestSending ? 'Testing...' : 'Test Zalo Notify' }}
              </button>
            </div>
          </form>
        </template>

        <div class="settings-divider"></div>

        <form class="form-grid" @submit.prevent="saveMyPassword">
          <label class="field"><span>Current password (optional first set)</span><input v-model="passwordForm.current_password" type="password" /></label>
          <label class="field"><span>New password</span><input v-model="passwordForm.new_password" type="password" minlength="6" /></label>
          <label class="field full"><span>Confirm new password</span><input v-model="passwordForm.confirm_password" type="password" minlength="6" /></label>
          <div class="field actions-row full">
            <button class="primary-btn save-btn" type="submit" :disabled="passwordSaving">
              {{ passwordSaving ? 'Saving...' : 'Change Password' }}
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="toast.show" class="toast" :class="{ error: toast.error }">{{ toast.message }}</div>
    </template>
  </div>
</template>
