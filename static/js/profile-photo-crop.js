/**
 * Profile photo picker with Cropper.js (vendored in static/vendor/cropper/).
 * Crops to 512×512 JPEG before submitting the existing Django form field.
 */
(function () {
  'use strict';

  var MAX_BYTES = 5 * 1024 * 1024;
  var ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
  var CROP_SIZE = 512;

  function initProfilePhotoCrop(root) {
    var fileInput = root.querySelector('.profile-photo-file-input');
    var chooseBtn = root.querySelector('.profile-photo-choose-btn');
    var modalEl = root.querySelector('.profile-photo-crop-modal');
    var cropImg = root.querySelector('.profile-photo-crop-image');
    var saveBtn = root.querySelector('.profile-photo-crop-save');
    var errorEl = root.querySelector('.profile-photo-error');
    var uploadForm = root.querySelector('.profile-photo-upload-form');

    if (!fileInput || !modalEl || !cropImg || !uploadForm || typeof Cropper === 'undefined') {
      return;
    }

    var cropper = null;
    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    function showError(msg) {
      if (!errorEl) return;
      errorEl.textContent = msg;
      errorEl.classList.remove('d-none');
    }

    function clearError() {
      if (!errorEl) return;
      errorEl.textContent = '';
      errorEl.classList.add('d-none');
    }

    if (chooseBtn) {
      chooseBtn.addEventListener('click', function () {
        clearError();
        fileInput.click();
      });
    }

    fileInput.addEventListener('change', function () {
      clearError();
      var file = this.files[0];
      if (!file) return;

      if (ALLOWED_TYPES.indexOf(file.type) === -1) {
        showError('Profile photo must be a JPG, PNG, or WebP image.');
        this.value = '';
        return;
      }
      if (file.size > MAX_BYTES) {
        showError('Profile photo must be 5 MB or smaller.');
        this.value = '';
        return;
      }

      var reader = new FileReader();
      reader.onload = function (e) {
        if (cropper) {
          cropper.destroy();
          cropper = null;
        }
        cropImg.src = e.target.result;
        modal.show();
        modalEl.addEventListener('shown.bs.modal', function onShown() {
          modalEl.removeEventListener('shown.bs.modal', onShown);
          cropper = new Cropper(cropImg, {
            aspectRatio: 1,
            viewMode: 1,
            dragMode: 'move',
            autoCropArea: 0.92,
            responsive: true,
            background: false,
            guides: false,
            center: true,
            highlight: false,
            movable: true,
            zoomable: true,
            scalable: false,
            rotatable: false,
          });
        });
      };
      reader.readAsDataURL(file);
    });

    modalEl.addEventListener('hidden.bs.modal', function () {
      if (cropper) {
        cropper.destroy();
        cropper = null;
      }
      cropImg.removeAttribute('src');
      cropImg.src = '';
      fileInput.value = '';
    });

    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        if (!cropper) return;
        var canvas = cropper.getCroppedCanvas({
          width: CROP_SIZE,
          height: CROP_SIZE,
          imageSmoothingEnabled: true,
          imageSmoothingQuality: 'high',
        });
        if (!canvas) {
          showError('Could not crop this image. Try another photo.');
          modal.hide();
          return;
        }
        canvas.toBlob(function (blob) {
          if (!blob) {
            showError('Could not process this image.');
            return;
          }
          var cropped = new File([blob], 'profile.jpg', {
            type: 'image/jpeg',
            lastModified: Date.now(),
          });
          var dt = new DataTransfer();
          dt.items.add(cropped);
          fileInput.files = dt.files;
          modal.hide();
          uploadForm.submit();
        }, 'image/jpeg', 0.92);
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-profile-photo-crop]').forEach(initProfilePhotoCrop);
  });
})();
