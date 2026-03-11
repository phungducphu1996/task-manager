<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

const AUTH_STORAGE_KEY = 'social_shared_auth'
const TIMELINE_PREFS_KEY = 'social_timeline_prefs_v1'
const TASK_NO_MEDIA_COLORS_KEY = 'social_timeline_task_no_media_colors_v1'
const DEFAULT_TIMELINE_NO_MEDIA_BG = '#f2f0e2'
const QUICK_NOTE_MAX_LENGTH = 256
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
const sellers = ref([])
const collections = ref([])
const hashtagGroups = ref([])
const hashtags = ref([])
const loading = ref(false)
const authLoading = ref(false)
const settingsOpen = ref(false)
const settingsTab = ref('collections')

const auth = reactive({
  token: '',
  user: null,
  username: '',
  password: ''
})

const visibleFields = reactive({
  type: true,
  airDate: true,
  assignee: true,
  missing: true
})

const detailOpen = ref(false)
const selectedTask = ref(null)
const selectedTaskId = ref(null)
const activeTab = ref('content')
const createMode = ref(false)
const createType = ref('story')

const draggingTaskId = ref(null)
const detailPendingMedia = ref([])
const failedTimelineThumbs = ref(new Set())
const timelineViewportRef = ref(null)
const timelinePrefs = reactive({
  dayWidth: 220,
  cardScale: 120,
  noMediaBg: DEFAULT_TIMELINE_NO_MEDIA_BG
})
const timelinePanState = reactive({
  active: false,
  startX: 0,
  startScrollLeft: 0
})
const timelineAutoFocusDone = ref(false)
const taskNoMediaColors = ref({})
const notePreview = reactive({
  open: false,
  taskId: '',
  title: '',
  note: '',
  draft: '',
  airDate: null,
  source: '',
  saving: false
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
  caption: '',
  hashtags: '',
  mentions: '',
  assignee_name: '',
  campaign_name: '',
  air_date: ''
})

const mediaForm = reactive({
  product_url: ''
})

const checklistText = ref('')
const commentText = ref('')
const statusValue = ref('idea')

const collectionForm = reactive({
  name: '',
  color: '',
  description: ''
})

const hashtagGroupForm = reactive({
  name: '',
  scope: 'global'
})

const hashtagForm = reactive({
  group_id: '',
  tag: ''
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

function sanitizeHexColor(value, fallback = DEFAULT_TIMELINE_NO_MEDIA_BG) {
  const raw = String(value || '').trim()
  return /^#[0-9a-fA-F]{6}$/.test(raw) ? raw.toLowerCase() : fallback
}

function normalizeQuickNote(value) {
  const raw = String(value ?? '')
  if (!raw.trim()) return ''
  return raw.trim().slice(0, QUICK_NOTE_MAX_LENGTH)
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
  notePreview.open = true
  notePreview.taskId = String(task?.id || '')
  notePreview.title = task?.title || 'Untitled task'
  notePreview.note = note
  notePreview.draft = note
  notePreview.airDate = task?.air_date || null
  notePreview.source = source
}

function closeNotePreview() {
  notePreview.open = false
  notePreview.taskId = ''
  notePreview.title = ''
  notePreview.note = ''
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

function applyQuickNoteToLocalState(taskId, noteValue) {
  calendarTasks.value = calendarTasks.value.map((task) => (task.id === taskId ? { ...task, quick_note: noteValue } : task))

  const nextKanban = {}
  statusOrder.forEach((status) => {
    nextKanban[status] = (kanban.value[status] || []).map((task) => (task.id === taskId ? { ...task, quick_note: noteValue } : task))
  })
  kanban.value = nextKanban

  if (selectedTask.value?.id === taskId) {
    selectedTask.value = { ...selectedTask.value, quick_note: noteValue }
    contentForm.quick_note = noteValue || ''
  }
}

async function saveNoteFromPreview() {
  if (!notePreview.taskId) return
  const normalizedDraft = normalizeQuickNote(notePreview.draft)
  const normalizedCurrent = normalizeQuickNote(notePreview.note)
  if (normalizedDraft === normalizedCurrent) {
    showToast('No note changes yet')
    return
  }
  try {
    notePreview.saving = true
    await requestJson(`/tasks/${notePreview.taskId}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'PATCH',
      body: {
        quick_note: normalizedDraft || null
      }
    })
    notePreview.note = normalizedDraft
    notePreview.draft = normalizedDraft
    applyQuickNoteToLocalState(notePreview.taskId, normalizedDraft || null)
    showToast('Quick note saved')
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
    timelinePrefs.noMediaBg = sanitizeHexColor(parsed?.noMediaBg, timelinePrefs.noMediaBg)
  } catch {
    // ignore invalid localStorage
  }
}

function loadTaskNoMediaColors() {
  try {
    const raw = localStorage.getItem(TASK_NO_MEDIA_COLORS_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return
    const cleaned = Object.fromEntries(
      Object.entries(parsed)
        .filter(([taskId]) => Boolean(String(taskId || '').trim()))
        .map(([taskId, color]) => [taskId, sanitizeHexColor(color)])
    )
    taskNoMediaColors.value = cleaned
  } catch {
    // ignore invalid localStorage
  }
}

function getTaskNoMediaColor(taskId) {
  const taskKey = String(taskId || '')
  const raw = taskNoMediaColors.value[taskKey]
  if (!raw) return timelinePrefs.noMediaBg
  return sanitizeHexColor(raw, timelinePrefs.noMediaBg)
}

function setTaskNoMediaColor(taskId, color) {
  const taskKey = String(taskId || '')
  if (!taskKey) return
  taskNoMediaColors.value = {
    ...taskNoMediaColors.value,
    [taskKey]: sanitizeHexColor(color, timelinePrefs.noMediaBg)
  }
}

function focusTimelineToToday() {
  const viewport = timelineViewportRef.value
  if (!viewport || timeline.value.totalDays <= 0) return
  const index = clamp(Number(timeline.value.todayIndex || 0), 0, Math.max(timeline.value.totalDays - 1, 0))
  const centered = index * timeline.value.dayWidth - Math.max(0, Math.round((viewport.clientWidth - timeline.value.dayWidth) / 2))
  viewport.scrollLeft = Math.max(0, centered)
}

function startTimelinePan(event) {
  if (event.button !== 0) return
  if (event.target?.closest?.('.timeline-item, .timeline-create-overlay, .timeline-create-btn, .timeline-card-color, button, input, textarea, select, a, label')) return
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

function inferMediaKind(file) {
  return String(file?.type || '').startsWith('video/') ? 'video' : 'image'
}

function fileSignature(file) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function mapFilesToPendingItems(fileList) {
  const files = Array.from(fileList || [])
  return files.map((file) => ({
    id: crypto.randomUUID(),
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
    auth.user = result.user || null
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
      role: me.role
    }
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

async function loadSellers() {
  if (!auth.token) return
  try {
    sellers.value = await requestJson('/sellers')
  } catch {
    sellers.value = []
  }
}

async function loadCollections() {
  if (!auth.token) return
  try {
    collections.value = await requestJson('/collections')
  } catch {
    collections.value = []
  }
}

async function loadHashtagGroups() {
  if (!auth.token) return
  try {
    hashtagGroups.value = await requestJson('/hashtag-groups')
    if (!hashtagForm.group_id && hashtagGroups.value.length > 0) {
      hashtagForm.group_id = hashtagGroups.value[0].id
    }
  } catch {
    hashtagGroups.value = []
  }
}

async function loadHashtags() {
  if (!auth.token) return
  try {
    hashtags.value = await requestJson('/hashtags')
  } catch {
    hashtags.value = []
  }
}

async function bootstrapAfterAuth() {
  await Promise.all([loadDashboard(), loadSellers(), loadCollections(), loadHashtagGroups(), loadHashtags()])
  if (!timelineAutoFocusDone.value) {
    await nextTick()
    focusTimelineToToday()
    timelineAutoFocusDone.value = true
  }
  openFromPath()
}

async function createCollection() {
  const name = collectionForm.name.trim()
  if (!name) return
  try {
    await requestJson('/collections', {
      method: 'POST',
      body: {
        name,
        color: collectionForm.color.trim() || null,
        description: collectionForm.description.trim() || null
      }
    })
    collectionForm.name = ''
    collectionForm.color = ''
    collectionForm.description = ''
    await loadCollections()
    showToast('Collection created')
  } catch (error) {
    showToast(`Create collection failed (${error.message})`, true)
  }
}

async function deleteCollection(collectionId) {
  try {
    await requestJson(`/collections/${collectionId}`, { method: 'DELETE' })
    await loadCollections()
    showToast('Collection deleted')
  } catch (error) {
    showToast(`Delete collection failed (${error.message})`, true)
  }
}

async function createHashtagGroup() {
  const name = hashtagGroupForm.name.trim()
  if (!name) return
  try {
    await requestJson('/hashtag-groups', {
      method: 'POST',
      body: {
        name,
        scope: hashtagGroupForm.scope
      }
    })
    hashtagGroupForm.name = ''
    hashtagGroupForm.scope = 'global'
    await loadHashtagGroups()
    showToast('Hashtag group created')
  } catch (error) {
    showToast(`Create group failed (${error.message})`, true)
  }
}

async function createHashtag() {
  const tag = hashtagForm.tag.trim()
  if (!hashtagForm.group_id || !tag) return
  try {
    await requestJson('/hashtags', {
      method: 'POST',
      body: {
        group_id: hashtagForm.group_id,
        tag
      }
    })
    hashtagForm.tag = ''
    await loadHashtags()
    showToast('Hashtag added')
  } catch (error) {
    showToast(`Add hashtag failed (${error.message})`, true)
  }
}

async function deleteHashtag(hashtagId) {
  try {
    await requestJson(`/hashtags/${hashtagId}`, { method: 'DELETE' })
    await loadHashtags()
    showToast('Hashtag deleted')
  } catch (error) {
    showToast(`Delete hashtag failed (${error.message})`, true)
  }
}

const flatTasks = computed(() => statusOrder.flatMap((status) => kanban.value[status] || []))

const summaryById = computed(() => {
  const map = new Map()
  flatTasks.value.forEach((task) => map.set(task.id, task))
  return map
})

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

const assigneeOptions = computed(() => {
  const options = new Set()
  sellers.value.forEach((seller) => {
    if (seller.username) options.add(seller.username)
  })
  flatTasks.value.forEach((task) => {
    if (task.assignee) options.add(task.assignee)
  })
  if (contentForm.assignee_name) options.add(contentForm.assignee_name)
  return [...options].sort((a, b) => a.localeCompare(b))
})

const timeline = computed(() => {
  const items = calendarTasks.value.filter((row) => row.air_date)
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const validDates = items
    .map((row) => new Date(row.air_date))
    .filter((date) => !Number.isNaN(date.valueOf()))

  const minSource = validDates.length > 0 ? new Date(Math.min(...validDates.map((d) => d.valueOf()), now.valueOf())) : now
  const maxSource = validDates.length > 0 ? new Date(Math.max(...validDates.map((d) => d.valueOf()), now.valueOf())) : now

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
  const laneTopOffset = createRowHeight + 10
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
        no_media_bg: getTaskNoMediaColor(task.id),
        style: {
          top: `${laneTopOffset + lane * rowHeight}px`,
          left: `${dayIndex * dayWidth + 8}px`,
          width: `${widthPx}px`,
          '--timeline-card-no-media-bg': getTaskNoMediaColor(task.id)
        }
      }
    })
    .filter(Boolean)

  return {
    days,
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
  const missing = Number(task.missing_count || 0)
  const badges = []
  if (visibleFields.type) badges.push({ text: String(task.type || '').toUpperCase(), className: typeClass(task.type) })
  if (visibleFields.airDate) badges.push({ text: `📅 ${fmtDate(task.air_date, false)}`, className: '' })
  if (visibleFields.assignee) badges.push({ text: task.assignee || 'Unassigned', className: '' })
  if (visibleFields.missing) badges.push({ text: missing > 0 ? `Missing ${missing}` : 'Complete', className: '' })
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
  return window.location.pathname.startsWith('/dashboard') ? '/dashboard' : '/'
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
  contentForm.caption = ''
  contentForm.hashtags = ''
  contentForm.mentions = ''
  contentForm.assignee_name = ''
  contentForm.campaign_name = ''
  contentForm.air_date = ''
  mediaForm.product_url = ''
  checklistText.value = ''
  commentText.value = ''
  statusValue.value = statusOrder.includes(defaultStatus) ? defaultStatus : 'idea'
  createType.value = 'story'
  clearPendingMedia(detailPendingMedia)
}

function openCreateInColumn(defaultStatus = 'idea') {
  createMode.value = true
  detailOpen.value = true
  selectedTask.value = null
  selectedTaskId.value = null
  activeTab.value = 'content'
  resetDetailDraft(defaultStatus)
  window.history.pushState({}, '', dashboardBasePath())
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
    createMode.value = false
    selectedTask.value = task
    selectedTaskId.value = task.id
    detailOpen.value = true
    activeTab.value = 'content'

    const summary = summaryById.value.get(task.id)
    contentForm.title = task.title || ''
    contentForm.quick_note = normalizeQuickNote(task.quick_note || summary?.quick_note || '')
    contentForm.caption = task.caption || ''
    contentForm.hashtags = (task.hashtags || []).join(' ')
    contentForm.mentions = (task.mentions || []).join(' ')
    contentForm.assignee_name = summary?.assignee || ''
    contentForm.campaign_name = summary?.campaign || ''
    contentForm.air_date = toInputDatetime(task.air_date)

    mediaForm.product_url = task.product_url || ''
    clearPendingMedia(detailPendingMedia)

    checklistText.value = (task.checklist_items || [])
      .slice()
      .sort((a, b) => a.position - b.position)
      .map((item) => `${item.is_done ? '[x]' : '[ ]'} ${item.title}`)
      .join('\n')

    commentText.value = ''
    statusValue.value = task.status

    if (push) {
      window.history.pushState({}, '', `${dashboardBasePath()}/tasks/${task.id}`)
    }
  } catch (error) {
    showToast(`Failed to open task (${error.message})`, true)
  }
}

function closeDetail() {
  createMode.value = false
  detailOpen.value = false
  selectedTask.value = null
  selectedTaskId.value = null
  closeNotePreview()
  clearPendingMedia(detailPendingMedia)
  window.history.pushState({}, '', dashboardBasePath())
}

async function refreshAndKeepDetail() {
  const current = selectedTaskId.value
  await loadDashboard()
  if (current) {
    await openTask(current, false)
  }
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
    caption: contentForm.caption.trim() || null,
    hashtags: parseSpaceList(contentForm.hashtags),
    mentions: parseSpaceList(contentForm.mentions),
    product_url: mediaForm.product_url.trim() || null,
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
      caption: contentForm.caption,
      hashtags: parseSpaceList(contentForm.hashtags),
      mentions: parseSpaceList(contentForm.mentions)
    }
    if (contentForm.assignee_name.trim()) payload.assignee_name = contentForm.assignee_name.trim()
    if (contentForm.campaign_name.trim()) payload.campaign_name = contentForm.campaign_name.trim()
    if (contentForm.air_date) payload.air_date = contentForm.air_date

    await requestJson(`/tasks/${selectedTaskId.value}?actor_name=${encodeURIComponent(actorName())}`, {
      method: 'PATCH',
      body: payload
    })
    showToast('Content saved')
    await refreshAndKeepDetail()
  } catch (error) {
    showToast(`Save failed (${error.message})`, true)
  }
}

async function handleAttachMedia() {
  if (createMode.value) {
    if (detailPendingMedia.value.length === 0 && !mediaForm.product_url.trim()) {
      showToast('Add media files or product URL first', true)
      return
    }
    showToast('Media is queued. Click Save Content to create task.')
    return
  }
  if (!selectedTaskId.value) return
  const productUrl = mediaForm.product_url.trim()
  const pendingFiles = detailPendingMedia.value
  if (!productUrl && pendingFiles.length === 0) {
    showToast('Add media files or product URL first', true)
    return
  }
  try {
    if (productUrl) {
      await requestJson(`/tasks/${selectedTaskId.value}?actor_name=${encodeURIComponent(actorName())}`, {
        method: 'PATCH',
        body: { product_url: productUrl }
      })
    }
    if (pendingFiles.length > 0) {
      await uploadPendingMedia(selectedTaskId.value, pendingFiles, actorName())
    }
    clearPendingMedia(detailPendingMedia)
    showToast('Media/Product updated')
    await refreshAndKeepDetail()
    activeTab.value = 'media'
  } catch (error) {
    showToast(`Attach failed (${error.message})`, true)
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
  if (!content) return
  try {
    await requestJson(`/tasks/${selectedTaskId.value}/comments`, {
      method: 'POST',
      body: { content, user_name: actorName() }
    })
    commentText.value = ''
    showToast('Comment added')
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

async function handleSeedDemo() {
  const now = new Date()
  const plusDays = (days, hour) => {
    const date = new Date(now)
    date.setDate(date.getDate() + days)
    date.setHours(hour, 0, 0, 0)
    return toInputDatetime(date)
  }

  const demoTasks = [
    {
      title: 'Demo Story Launch',
      type: 'story',
      status: 'idea',
      air_date: plusDays(1, 19),
      assignee_name: 'Linh',
      campaign_name: 'SpringBrand',
      hashtags: ['#spring', '#brand'],
      media_urls: ['https://cdn.example.com/demo-story.jpg']
    },
    {
      title: 'Demo Reel Product',
      type: 'reel',
      status: 'design',
      air_date: plusDays(2, 19),
      assignee_name: 'An',
      campaign_name: 'ProductDrop',
      caption: 'Product tease and CTA',
      media_urls: ['https://cdn.example.com/demo-reel.mp4']
    },
    {
      title: 'Demo Post Recap',
      type: 'post',
      status: 'ready',
      air_date: plusDays(0, 19),
      assignee_name: 'Ram',
      campaign_name: 'WeeklyRecap',
      caption: 'Recap highlights',
      media_urls: ['https://cdn.example.com/demo-post.jpg']
    }
  ]

  try {
    for (const payload of demoTasks) {
      await requestJson('/tasks', { method: 'POST', body: payload })
    }
    showToast('Demo tasks created')
    await loadDashboard()
  } catch (error) {
    showToast(`Seed failed (${error.message})`, true)
  }
}

function onDragStart(taskId) {
  draggingTaskId.value = taskId
}

function onDragEnd() {
  draggingTaskId.value = null
}

async function onDropToStatus(status) {
  if (!draggingTaskId.value) return
  const taskId = draggingTaskId.value
  draggingTaskId.value = null
  await updateTaskStatus(taskId, status)
}

function openFromPath() {
  const match = window.location.pathname.match(/^\/dashboard\/tasks\/([^/]+)$/)
  if (match) {
    openTask(match[1], false)
  }
}

onMounted(async () => {
  loadTimelinePrefs()
  loadTaskNoMediaColors()

  const rawAuth = localStorage.getItem(AUTH_STORAGE_KEY)
  if (rawAuth) {
    try {
      const parsed = JSON.parse(rawAuth)
      auth.token = parsed.token || ''
      auth.user = parsed.user || null
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
  window.addEventListener('popstate', openFromPath)
})

watch(
  () => [timelinePrefs.dayWidth, timelinePrefs.cardScale, timelinePrefs.noMediaBg],
  ([dayWidth, cardScale, noMediaBg]) => {
    localStorage.setItem(
      TIMELINE_PREFS_KEY,
      JSON.stringify({
        dayWidth: clamp(Number(dayWidth), 140, 320),
        cardScale: clamp(Number(cardScale), 90, 200),
        noMediaBg: sanitizeHexColor(noMediaBg),
      })
    )
  }
)

watch(
  taskNoMediaColors,
  (map) => {
    localStorage.setItem(TASK_NO_MEDIA_COLORS_KEY, JSON.stringify(map || {}))
  },
  { deep: true }
)

onUnmounted(() => {
  window.removeEventListener('popstate', openFromPath)
  clearPendingMedia(detailPendingMedia)
  endTimelinePan()
})
</script>

<template>
  <div>
    <section v-if="!auth.token || !auth.user" class="login-shell">
      <div class="topo-overlay" aria-hidden="true"></div>
      <div class="login-card card-surface">
        <p class="eyebrow">Shared Auth</p>
        <h1>Login with Etsy Account</h1>
        <p class="subtle">Use the same credentials as Etsy Shop Manager.</p>
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
          <a class="menu-item active" href="/dashboard">Overview</a>
          <a class="menu-item" href="#board">Kanban</a>
          <a class="menu-item" href="#timeline">Calendar</a>
          <a class="menu-item" href="#analytics">Analytics</a>
        </nav>
        <div class="actions">
          <button class="ghost-btn" type="button" @click="settingsOpen = true">Settings</button>
          <button class="ghost-btn" type="button" @click="loadDashboard">Refresh</button>
          <button class="ghost-btn" type="button" @click="handleRunReminders">Run Reminders</button>
          <button class="ghost-btn" type="button" @click="handleSeedDemo">Seed Demo</button>
          <button class="ghost-btn" type="button" @click="logout">Logout</button>
          <span class="pill user-pill">{{ auth.user.username }} ({{ auth.user.role }})</span>
        </div>
      </header>

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
              <label><input v-model="visibleFields.missing" type="checkbox" /> Missing</label>
            </div>

            <div class="kanban-columns">
              <section
                v-for="status in statusOrder"
                :key="status"
                class="kanban-col"
                :data-status="status"
                @dragover.prevent
                @drop="onDropToStatus(status)"
              >
                <header>
                  <strong>{{ statusLabels[status] }}</strong>
                  <span class="pill">{{ kanban[status]?.length || 0 }}</span>
                </header>
                <ul class="drop-zone">
                  <li
                    v-for="task in kanban[status]"
                    :key="task.id"
                    class="kanban-card"
                    :class="typeClass(task.type)"
                    draggable="true"
                    @dragstart="onDragStart(task.id)"
                    @dragend="onDragEnd"
                    @click="openTask(task.id)"
                  >
                    <strong>{{ task.title }}</strong>
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
                <label class="timeline-color-control">
                  No Media Color
                  <input v-model="timelinePrefs.noMediaBg" type="color" />
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
                  '--timeline-media-height': `${timeline.mediaHeight}px`,
                  '--timeline-no-media-bg': timelinePrefs.noMediaBg
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
                  <template v-if="timeline.cards.length === 0">
                    <p style="padding:16px">Set air_date to render roadmap bars.</p>
                  </template>
                  <div
                    v-for="task in timeline.cards"
                    :key="task.id"
                    class="timeline-item timeline-tile"
                    :class="task.status"
                    :style="task.style"
                    role="button"
                    tabindex="0"
                    @click="openTask(task.id)"
                    @keydown.enter.prevent="openTask(task.id)"
                    @keydown.space.prevent="openTask(task.id)"
                  >
                    <div class="timeline-tile-head">
                      <span class="timeline-platform">IG</span>
                      <div class="timeline-head-right">
                        <span class="timeline-type-chip" :class="typeClass(task.type)">
                          {{ String(task.type || '').toUpperCase() || 'POST' }}
                        </span>
                        <label v-if="!isTimelineThumbVisible(task.media_thumbnail)" class="timeline-card-color">
                          <span>Note</span>
                          <input
                            :value="task.no_media_bg"
                            type="color"
                            @click.stop
                            @mousedown.stop
                            @keydown.stop
                            @input="setTaskNoMediaColor(task.id, $event.target.value)"
                          />
                        </label>
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
                        :title="normalizeQuickNote(task.quick_note)"
                        @click.stop="openNotePreview(task, 'timeline')"
                      >
                        {{ previewQuickNote(task.quick_note, 118) }}
                      </button>
                      <div v-else class="timeline-no-media">No media yet</div>
                      <div v-if="task.type === 'story' && isTimelineThumbVisible(task.media_thumbnail)" class="timeline-story-overlay">
                        <span class="timeline-story-icon">+</span>
                      </div>
                    </div>
                    <button
                      v-if="task.type !== 'story' && isTimelineThumbVisible(task.media_thumbnail) && normalizeQuickNote(task.quick_note)"
                      type="button"
                      class="timeline-content-snippet note-preview-btn"
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
    </main>

    <section v-if="detailOpen" class="detail card-surface open">
      <div class="detail-head">
        <h2>{{ createMode ? 'Create Task' : selectedTask?.title }}</h2>
        <div class="detail-head-actions">
          <button class="ghost-btn" type="button" @click="closeDetail">Close</button>
          <button v-if="!createMode" class="ghost-btn" type="button" @click="handleDeleteTask">Delete</button>
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
        <p class="subtle">
          {{ createMode
            ? `${String(createType || '').toUpperCase()} · ${contentForm.air_date ? fmtDate(contentForm.air_date) : 'No air date'}`
            : `${String(selectedTask?.type || '').toUpperCase()} · ${fmtDate(selectedTask?.air_date)} · ${
                (selectedTask?.validate?.missing_fields || []).length > 0
                  ? `Missing: ${(selectedTask?.validate?.missing_fields || []).join(', ')}`
                  : 'Ready for full package.'
              }` }}
        </p>
      </div>

      <div class="detail-tabs">
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'content' }" @click="activeTab = 'content'">Content</button>
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'media' }" @click="activeTab = 'media'">Media</button>
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'checklist' }" @click="activeTab = 'checklist'">Checklist</button>
        <button v-if="!createMode" type="button" class="tab-btn" :class="{ active: activeTab === 'comments' }" @click="activeTab = 'comments'">Comments</button>
        <button v-if="!createMode" type="button" class="tab-btn" :class="{ active: activeTab === 'activity' }" @click="activeTab = 'activity'">Activity</button>
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
          <label class="field full"><span>Caption</span><textarea v-model="contentForm.caption" rows="7"></textarea></label>
          <label class="field"><span>Hashtags (space separated)</span><input v-model="contentForm.hashtags" type="text" /></label>
          <label class="field"><span>Mentions (space separated)</span><input v-model="contentForm.mentions" type="text" /></label>
          <label class="field">
            <span>Assignee Name</span>
            <select v-model="contentForm.assignee_name">
              <option value="">{{ createMode ? 'Unassigned' : 'Unchanged' }}</option>
              <option v-for="name in assigneeOptions" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="field"><span>Campaign Name</span><input v-model="contentForm.campaign_name" type="text" /></label>
          <label class="field"><span>Air Date</span><input v-model="contentForm.air_date" type="datetime-local" /></label>
          <div class="field actions-row"><button class="primary-btn" type="submit">{{ createMode ? 'Create Task' : 'Save Content' }}</button></div>
        </form>
      </div>

      <div v-show="activeTab === 'media'" class="tab-panel active">
        <form class="form-grid" @submit.prevent="handleAttachMedia">
          <label class="field full"><span>Product URL</span><input v-model="mediaForm.product_url" type="url" /></label>
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
          <div class="field actions-row"><button class="primary-btn" type="submit">Attach Media</button></div>
        </form>
        <div v-if="!createMode" class="list-shell">
          <article v-for="asset in (selectedTask?.assets || []).filter((item) => !isDemoAssetUrl(item.url))" :key="asset.id" class="list-item">
            <img v-if="asset.kind === 'image'" :src="asset.url" alt="" class="asset-thumb" />
            <video v-else :src="asset.url" class="asset-thumb" controls preload="metadata"></video>
            <strong>{{ String(asset.kind || '').toUpperCase() }}</strong>
            <p class="meta">{{ asset.url }}</p>
          </article>
          <article v-if="(selectedTask?.assets || []).filter((item) => !isDemoAssetUrl(item.url)).length === 0" class="list-item">
            <p class="meta">No real media attached yet. Upload files to see preview.</p>
          </article>
        </div>
      </div>

      <div v-show="activeTab === 'checklist'" class="tab-panel active">
        <form class="form-grid" @submit.prevent="handleSaveChecklist">
          <label class="field full"><span>Checklist lines ([x] done or [ ] todo)</span><textarea v-model="checklistText" rows="7"></textarea></label>
          <div class="field actions-row"><button class="primary-btn" type="submit">Save Checklist</button></div>
        </form>
      </div>

      <div v-if="!createMode" v-show="activeTab === 'comments'" class="tab-panel active">
        <form class="inline-form" @submit.prevent="handleAddComment">
          <input v-model="commentText" type="text" placeholder="Write comment..." />
          <button class="primary-btn" type="submit">Send</button>
        </form>
        <div class="list-shell">
          <article v-for="comment in (selectedTask?.comments || []).slice().sort((a,b)=>new Date(a.created_at)-new Date(b.created_at))" :key="comment.id" class="list-item">
            <strong>{{ comment.user_id || 'User' }}</strong>
            <p>{{ comment.content }}</p>
            <p class="meta">{{ fmtDate(comment.created_at) }}</p>
          </article>
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
    </section>

    <div class="modal-backdrop" :class="{ open: notePreview.open }" :aria-hidden="notePreview.open ? 'false' : 'true'" @click="closeNotePreview">
      <section class="modal-card note-preview-card" role="dialog" aria-modal="true" aria-labelledby="notePreviewTitle" @click.stop>
        <header class="modal-head">
          <h3 id="notePreviewTitle">Quick Note</h3>
          <button class="ghost-btn" type="button" @click="closeNotePreview">Close</button>
        </header>
        <p class="meta note-preview-meta">
          {{ notePreview.title }} · {{ notePreview.airDate ? fmtDate(notePreview.airDate) : 'No air date' }}
        </p>
        <textarea
          v-model="notePreview.draft"
          class="note-preview-input"
          :maxlength="QUICK_NOTE_MAX_LENGTH"
          rows="6"
          placeholder="Write quick note..."
        ></textarea>
        <p class="meta note-preview-meta note-preview-counter">{{ (notePreview.draft || '').length }}/{{ QUICK_NOTE_MAX_LENGTH }}</p>
        <div class="note-preview-actions">
          <button class="ghost-btn" type="button" :disabled="notePreview.saving" @click="saveNoteFromPreview">
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

    <div class="modal-backdrop" :class="{ open: settingsOpen }" :aria-hidden="settingsOpen ? 'false' : 'true'">
      <section class="modal-card settings-card" role="dialog" aria-modal="true" aria-labelledby="settingsTitle" @click.stop>
        <header class="modal-head">
          <h3 id="settingsTitle">Settings</h3>
          <button class="ghost-btn" type="button" @click="settingsOpen = false">Close</button>
        </header>
        <div class="detail-tabs">
          <button type="button" class="tab-btn" :class="{ active: settingsTab === 'collections' }" @click="settingsTab = 'collections'">Collections</button>
          <button type="button" class="tab-btn" :class="{ active: settingsTab === 'hashtags' }" @click="settingsTab = 'hashtags'">Hashtags</button>
          <button type="button" class="tab-btn" :class="{ active: settingsTab === 'sellers' }" @click="settingsTab = 'sellers'">Sellers</button>
        </div>

        <div v-show="settingsTab === 'collections'" class="tab-panel active">
          <form class="form-grid" @submit.prevent="createCollection">
            <label class="field"><span>Name</span><input v-model="collectionForm.name" type="text" /></label>
            <label class="field"><span>Color</span><input v-model="collectionForm.color" type="text" placeholder="#ffce62" /></label>
            <label class="field full"><span>Description</span><input v-model="collectionForm.description" type="text" /></label>
            <div class="field actions-row full"><button class="primary-btn" type="submit">Add Collection</button></div>
          </form>
          <div class="list-shell">
            <article v-for="collection in collections" :key="collection.id" class="list-item">
              <strong>{{ collection.name }}</strong>
              <p class="meta">{{ collection.description || 'No description' }}</p>
              <button class="ghost-btn" type="button" @click="deleteCollection(collection.id)">Delete</button>
            </article>
          </div>
        </div>

        <div v-show="settingsTab === 'hashtags'" class="tab-panel active">
          <form class="form-grid" @submit.prevent="createHashtagGroup">
            <label class="field"><span>Group name</span><input v-model="hashtagGroupForm.name" type="text" /></label>
            <label class="field">
              <span>Scope</span>
              <select v-model="hashtagGroupForm.scope">
                <option value="global">Global</option>
                <option value="campaign">Campaign</option>
                <option value="type">Type</option>
              </select>
            </label>
            <div class="field actions-row full"><button class="primary-btn" type="submit">Add Group</button></div>
          </form>
          <form class="form-grid" @submit.prevent="createHashtag">
            <label class="field">
              <span>Group</span>
              <select v-model="hashtagForm.group_id">
                <option v-for="group in hashtagGroups" :key="group.id" :value="group.id">{{ group.name }}</option>
              </select>
            </label>
            <label class="field"><span>Hashtag</span><input v-model="hashtagForm.tag" type="text" placeholder="#new" /></label>
            <div class="field actions-row full"><button class="primary-btn" type="submit">Add Hashtag</button></div>
          </form>
          <div class="list-shell">
            <article v-for="tag in hashtags" :key="tag.id" class="list-item">
              <strong>{{ tag.tag }}</strong>
              <p class="meta">Usage: {{ tag.usage_count }}</p>
              <button class="ghost-btn" type="button" @click="deleteHashtag(tag.id)">Delete</button>
            </article>
          </div>
        </div>

        <div v-show="settingsTab === 'sellers'" class="tab-panel active">
          <div class="list-shell">
            <article v-for="seller in sellers" :key="seller.id" class="list-item">
              <strong>{{ seller.username }}</strong>
              <p class="meta">{{ seller.id }}</p>
            </article>
            <article v-if="sellers.length === 0" class="list-item"><p class="meta">No seller data from Etsy yet.</p></article>
          </div>
        </div>
      </section>
    </div>

    <div v-if="toast.show" class="toast" :class="{ error: toast.error }">{{ toast.message }}</div>
    </template>
  </div>
</template>
