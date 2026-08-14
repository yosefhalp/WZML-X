#!/usr/bin/env bash
set -Eeuo pipefail

# הכלי מקבל תיקיית חבילה פתוחה או ארכיון tar ומוודא שלמות בלי לחשוף סודות.
input_path="${1:-.}"
temporary_dir=""
if [[ -f "${input_path}" ]]; then
  temporary_dir="$(mktemp -d)"
  trap 'rm -rf "${temporary_dir}"' EXIT
  tar -C "${temporary_dir}" -xf "${input_path}"
  package_dir="$(find "${temporary_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
else
  package_dir="$(cd "${input_path}" && pwd)"
fi
[[ -s "${package_dir}/manifest.json" && -s "${package_dir}/SHA256SUMS" ]] || { echo "החבילה חסרה manifest או קובץ בדיקות." >&2; exit 1; }
(cd "${package_dir}" && sha256sum -c SHA256SUMS >/dev/null)
for archive in "${package_dir}"/payload/*.tar.gz "${package_dir}"/payload/mongodb.archive.gz; do gzip -t "${archive}"; done
source_archive="${package_dir}/payload/wzmlx-source.tar.gz"
source_listing="$(tar -tzf "${source_archive}")"
for required_worker_file in \
  ./deploy/server/backup_worker.py \
  ./deploy/server/install-daily-backup.sh \
  ./deploy/server/full-backup.sh \
  ./deploy/server/full-restore.sh; do
  grep -Fxq "${required_worker_file}" <<<"${source_listing}" || {
    echo "ערכת הגיבוי חסרה רכיב של Worker הגיבוי." >&2
    exit 1
  }
done
shopt -s nullglob
image_archives=("${package_dir}"/images/*.tar.gz)
for image_archive in "${image_archives[@]}"; do
  gzip -t "${image_archive}"
  gzip -dc "${image_archive}" | tar -tf - >/dev/null
done
mode="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["mode"])' "${package_dir}/manifest.json")"
bot_api_mode="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("bot_api_restore_mode", "managed"))' "${package_dir}/manifest.json")"
expected_full_images=3
[[ "${bot_api_mode}" == "external" ]] && expected_full_images=2
if [[ "${mode}" == "full" && "${#image_archives[@]}" -ne "${expected_full_images}" ]]; then
  echo "מספר תמונות Docker אינו תואם לבעלות השירותים במפת הפריסה." >&2
  exit 1
fi
if [[ "${mode}" == "state" && "${#image_archives[@]}" -ne 0 ]]; then
  echo "ערכה מהירה אינה אמורה לכלול תמונות Docker." >&2
  exit 1
fi
python3 -m json.tool "${package_dir}/manifest.json" >/dev/null
echo "הגיבוי תקין וכל בדיקות השלמות עברו."
