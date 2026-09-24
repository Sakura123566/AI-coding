// 浏览器语音合成封装（SpeechSynthesis API）。
// 语音是纯前端能力，不依赖后端；voice_name 仅作音色偏好提示，最终由浏览器可用语音决定。

export function isSpeechSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    'SpeechSynthesisUtterance' in window
  )
}

// 根据 voice_name 提示 + 目标语言挑选浏览器语音；找不到则返回 undefined（用浏览器默认）
function pickVoice(voiceName?: string, lang = 'zh-CN'): SpeechSynthesisVoice | undefined {
  if (!isSpeechSupported()) return undefined
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return undefined
  if (voiceName) {
    const hit = voices.find((v) => v.name.toLowerCase().includes(voiceName.toLowerCase()))
    if (hit) return hit
  }
  // 优先同语言的语音
  const sameLang = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(lang.slice(0, 2)))
  if (sameLang) return sameLang
  return voices[0]
}

export function useSpeech() {
  function speak(
    text: string,
    opts: { voiceName?: string; rate?: number; pitch?: number; lang?: string } = {}
  ) {
    if (!isSpeechSupported() || !text) return
    cancel()
    const u = new SpeechSynthesisUtterance(text)
    const lang = opts.lang || 'zh-CN'
    const v = pickVoice(opts.voiceName, lang)
    if (v) u.voice = v
    u.lang = v?.lang || lang
    u.rate = opts.rate ?? 1
    u.pitch = opts.pitch ?? 1
    window.speechSynthesis.speak(u)
  }

  function cancel() {
    if (!isSpeechSupported()) return
    window.speechSynthesis.cancel()
  }

  return { speak, cancel, isSpeechSupported }
}
