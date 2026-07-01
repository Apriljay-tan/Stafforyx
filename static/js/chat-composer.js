/**
 * Shared messaging composer: image attach, voice record/upload, preview, submit.
 */
(function () {
  'use strict';

  var MAX_BYTES = 10 * 1024 * 1024;
  var IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
  var VOICE_TYPES = [
    'audio/webm', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/x-m4a',
    'audio/wav', 'audio/x-wav', 'audio/ogg', 'application/ogg', 'video/webm',
  ];

  function formatTimer(seconds) {
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return m + ':' + String(s).padStart(2, '0');
  }

  function extensionForMime(mime) {
    if (!mime) return 'webm';
    if (mime.indexOf('mpeg') !== -1 || mime.indexOf('mp3') !== -1) return 'mp3';
    if (mime.indexOf('mp4') !== -1 || mime.indexOf('m4a') !== -1) return 'm4a';
    if (mime.indexOf('wav') !== -1) return 'wav';
    if (mime.indexOf('ogg') !== -1) return 'ogg';
    return 'webm';
  }

  function isVoiceFile(file) {
    if (!file) return false;
    if (VOICE_TYPES.indexOf(file.type) !== -1) return true;
    return /\.(webm|mp3|m4a|wav|ogg)$/i.test(file.name || '');
  }

  function isImageFile(file) {
    if (!file) return false;
    if (IMAGE_TYPES.indexOf(file.type) !== -1) return true;
    return /\.(jpe?g|png|webp|gif)$/i.test(file.name || '');
  }

  function initChatComposer() {
    var box = document.getElementById('msgChatMessages');
    if (box) box.scrollTop = box.scrollHeight;

    var input = document.getElementById('msgChatComposerInput');
    var form = document.getElementById('msgChatComposerForm');
    var sendBtn = document.getElementById('msgChatSendBtn');
    var attachBtn = document.getElementById('msgChatAttachBtn');
    var attachInput = document.getElementById('msgChatAttachmentInput');
    var attachPreview = document.getElementById('msgChatAttachmentPreview');
    var voiceBtn = document.getElementById('msgChatVoiceBtn');
    var voiceUploadInput = document.getElementById('msgChatVoiceUploadInput');
    var voiceTimer = document.getElementById('msgChatVoiceTimer');

    if (!form || !attachInput) return;

    var pendingFile = null;
    var mediaRecorder = null;
    var mediaStream = null;
    var recordChunks = [];
    var recordStartedAt = null;
    var recordTimerId = null;
    var isRecording = false;

    function setAttachmentFile(file) {
      pendingFile = file || null;
      if (!file) {
        attachInput.value = '';
        return;
      }
      var dt = new DataTransfer();
      dt.items.add(file);
      attachInput.files = dt.files;
    }

    function clearPreview() {
      if (attachPreview) {
        attachPreview.innerHTML = '';
        attachPreview.classList.add('d-none');
      }
      pendingFile = null;
      attachInput.value = '';
    }

    function stopRecordingTimer() {
      if (recordTimerId) {
        clearInterval(recordTimerId);
        recordTimerId = null;
      }
      if (voiceTimer) {
        voiceTimer.textContent = '';
        voiceTimer.classList.add('d-none');
      }
    }

    function stopMediaTracks() {
      if (mediaStream) {
        mediaStream.getTracks().forEach(function (track) { track.stop(); });
        mediaStream = null;
      }
    }

    function resetVoiceButton() {
      isRecording = false;
      if (voiceBtn) {
        voiceBtn.classList.remove('recording');
        voiceBtn.innerHTML = '<i class="bi bi-mic"></i>';
        voiceBtn.title = 'Record voice message (or upload audio file)';
      }
      stopRecordingTimer();
      stopMediaTracks();
    }

    function showImagePreview(file) {
      if (!attachPreview) return;
      attachPreview.innerHTML = '';
      attachPreview.classList.remove('d-none');

      var row = document.createElement('div');
      row.className = 'msg-chat-attachment-preview-item';

      var thumb = document.createElement('img');
      thumb.className = 'msg-chat-attachment-preview-thumb';
      thumb.alt = '';
      row.appendChild(thumb);

      var meta = document.createElement('div');
      meta.className = 'msg-chat-attachment-preview-meta';
      var name = document.createElement('div');
      name.className = 'msg-chat-attachment-preview-name';
      name.textContent = file.name;
      meta.appendChild(name);
      var hint = document.createElement('div');
      hint.className = 'msg-chat-attachment-preview-hint';
      hint.textContent = 'Ready to send with your message';
      meta.appendChild(hint);
      row.appendChild(meta);

      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-secondary msg-chat-attachment-preview-remove';
      removeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
      removeBtn.addEventListener('click', clearPreview);
      row.appendChild(removeBtn);

      attachPreview.appendChild(row);

      var reader = new FileReader();
      reader.onload = function (e) { thumb.src = e.target.result; };
      reader.readAsDataURL(file);
    }

    function showVoicePreview(file, objectUrl) {
      if (!attachPreview) return;
      attachPreview.innerHTML = '';
      attachPreview.classList.remove('d-none');

      var row = document.createElement('div');
      row.className = 'msg-chat-attachment-preview-item msg-chat-attachment-preview-item--voice';

      var audio = document.createElement('audio');
      audio.controls = true;
      audio.preload = 'metadata';
      audio.className = 'msg-chat-voice-preview-player';
      audio.src = objectUrl || URL.createObjectURL(file);
      row.appendChild(audio);

      var meta = document.createElement('div');
      meta.className = 'msg-chat-attachment-preview-meta';
      var name = document.createElement('div');
      name.className = 'msg-chat-attachment-preview-name';
      name.textContent = 'Voice message';
      meta.appendChild(name);
      var hint = document.createElement('div');
      hint.className = 'msg-chat-attachment-preview-hint';
      hint.textContent = 'Ready to send';
      meta.appendChild(hint);
      row.appendChild(meta);

      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-sm btn-outline-secondary msg-chat-attachment-preview-remove';
      removeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
      removeBtn.addEventListener('click', function () {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        clearPreview();
      });
      row.appendChild(removeBtn);

      attachPreview.appendChild(row);
    }

    function applyAttachmentFile(file) {
      if (!file) return;
      if (file.size > MAX_BYTES) {
        alert('Attachment must be 10 MB or smaller.');
        return;
      }
      if (isImageFile(file)) {
        setAttachmentFile(file);
        showImagePreview(file);
        return;
      }
      if (isVoiceFile(file)) {
        setAttachmentFile(file);
        showVoicePreview(file);
        return;
      }
      alert('Unsupported file. Use an image or voice audio (WebM, MP3, M4A, WAV, OGG).');
    }

    function hasComposerContent() {
      var text = input ? input.value.trim() : '';
      return !!(text || pendingFile || (attachInput.files && attachInput.files[0]));
    }

    function startRecording() {
      if (!navigator.mediaDevices || !window.MediaRecorder) {
        if (voiceUploadInput) voiceUploadInput.click();
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        mediaStream = stream;
        recordChunks = [];
        var mimeType = '';
        if (MediaRecorder.isTypeSupported('audio/webm')) {
          mimeType = 'audio/webm';
        } else if (MediaRecorder.isTypeSupported('audio/ogg')) {
          mimeType = 'audio/ogg';
        }
        mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType: mimeType }) : new MediaRecorder(stream);
        mediaRecorder.ondataavailable = function (e) {
          if (e.data && e.data.size > 0) recordChunks.push(e.data);
        };
        mediaRecorder.onstop = function () {
          var type = mediaRecorder.mimeType || 'audio/webm';
          var blob = new Blob(recordChunks, { type: type });
          if (blob.size > MAX_BYTES) {
            alert('Recording is too large. Please record a shorter message (max 10 MB).');
            resetVoiceButton();
            return;
          }
          var ext = extensionForMime(type);
          var file = new File([blob], 'voice-message.' + ext, { type: type, lastModified: Date.now() });
          setAttachmentFile(file);
          showVoicePreview(file);
          resetVoiceButton();
        };
        mediaRecorder.start();
        isRecording = true;
        recordStartedAt = Date.now();
        if (voiceBtn) {
          voiceBtn.classList.add('recording');
          voiceBtn.innerHTML = '<i class="bi bi-stop-fill"></i>';
          voiceBtn.title = 'Stop recording';
        }
        if (voiceTimer) {
          voiceTimer.classList.remove('d-none');
          voiceTimer.textContent = '0:00';
        }
        recordTimerId = setInterval(function () {
          if (!voiceTimer || !recordStartedAt) return;
          var elapsed = Math.floor((Date.now() - recordStartedAt) / 1000);
          voiceTimer.textContent = formatTimer(elapsed);
        }, 500);
      }).catch(function () {
        alert('Microphone access was denied. You can upload an audio file instead.');
        if (voiceUploadInput) voiceUploadInput.click();
      });
    }

    function stopRecording() {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
      } else {
        resetVoiceButton();
      }
    }

    if (attachBtn && attachInput) {
      attachBtn.addEventListener('click', function () {
        attachInput.click();
      });
      attachInput.addEventListener('change', function () {
        var file = attachInput.files && attachInput.files[0];
        if (!file) {
          clearPreview();
          return;
        }
        clearPreview();
        applyAttachmentFile(file);
      });
    }

    if (voiceBtn) {
      voiceBtn.addEventListener('click', function () {
        if (isRecording) {
          stopRecording();
        } else {
          clearPreview();
          startRecording();
        }
      });
    }

    if (voiceUploadInput) {
      voiceUploadInput.addEventListener('change', function () {
        var file = voiceUploadInput.files && voiceUploadInput.files[0];
        voiceUploadInput.value = '';
        if (!file) return;
        clearPreview();
        applyAttachmentFile(file);
      });
    }

    if (input && form) {
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (hasComposerContent()) form.requestSubmit();
        }
      });
    }

    if (form && sendBtn) {
      form.addEventListener('submit', function (e) {
        if (isRecording) stopRecording();
        if (!hasComposerContent()) {
          e.preventDefault();
          return;
        }
        sendBtn.disabled = true;
        sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
      });
    }
  }

  document.addEventListener('DOMContentLoaded', initChatComposer);
})();
