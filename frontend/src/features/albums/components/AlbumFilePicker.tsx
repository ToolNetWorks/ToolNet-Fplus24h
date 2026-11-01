"use client";

import { useCallback, useEffect, useState } from "react";
import { Upload } from "lucide-react";

function Preview({ file, onError }: { file: File; onError: (file: File) => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const reader = new FileReader();
    reader.onload = () => setUrl(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => onError(file);
    reader.readAsDataURL(file);
    return () => { reader.onload = null; reader.onerror = null; reader.abort(); };
  }, [file, onError]);
  return url ? <img src={url} alt={`Xem trước ${file.name}`}
    className="aspect-square w-full rounded border object-cover" onError={() => onError(file)} /> : null;
}

export default function AlbumFilePicker({ files, onChange, disabled }: {
  files: File[];
  onChange: (files: File[]) => void;
  disabled: boolean;
}) {
  const [error, setError] = useState("");
  const invalidPreview = useCallback((file: File) => {
    setError(`${file.name}: không thể hiển thị ảnh, hãy chọn file khác.`);
    onChange(files.filter((selected) => selected !== file));
  }, [files, onChange]);
  function select(selected: File[]) {
    const errors: string[] = [];
    const allowed = new Set(["image/jpeg", "image/png", "image/webp"]);
    const valid = selected.filter((file) => {
      if (!allowed.has(file.type)) {
        errors.push(`${file.name}: chỉ hỗ trợ JPEG, PNG, WebP; HEIC/HEIF chưa được hỗ trợ.`);
        return false;
      }
      if (!file.size || file.size > 10 * 1024 * 1024) {
        errors.push(`${file.name}: ảnh phải có dung lượng từ 1 byte đến 10 MB.`);
        return false;
      }
      return true;
    });
    if (valid.length > 5) errors.push("Chỉ chọn tối đa 5 ảnh mỗi lượt.");
    onChange(valid.slice(0, 5));
    setError(errors.join(" "));
  }

  return <div className="space-y-3" onDragOver={(event) => { if (!disabled) event.preventDefault(); }}
    onDrop={(event) => { event.preventDefault(); if (!disabled) select(Array.from(event.dataTransfer.files)); }}>
    <label className={`relative flex w-full cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed border-slate-300 bg-white p-6 text-center focus-within:ring-2 focus-within:ring-blue-500 ${disabled ? "opacity-50" : "hover:border-blue-400"}`}>
      <Upload size={24} aria-hidden="true" />
      <span className="text-sm font-medium">Chọn ảnh từ thiết bị</span>
      <span className="text-xs text-slate-500">JPEG, PNG, WebP · tối đa 5 ảnh · 10 MB/ảnh</span>
      <input type="file" accept="image/*" multiple disabled={disabled}
        aria-label="Chọn ảnh từ thiết bị"
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        onChange={(event) => { select(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = ""; }} />
    </label>
    <p className="text-xs text-slate-600" aria-live="polite">{files.length} ảnh hợp lệ đã chọn</p>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    {files.length > 0 && <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {files.map((file, index) => <div key={`${file.name}-${file.lastModified}-${index}`} className="min-w-0">
        <Preview file={file} onError={invalidPreview} />
        <p className="truncate text-xs" title={file.name}>{file.name}</p>
        <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
        <button type="button" disabled={disabled} onClick={() => onChange(files.filter((_, i) => i !== index))} className="text-xs text-red-700">Bỏ ảnh</button>
      </div>)}
    </div>}
  </div>;
}
