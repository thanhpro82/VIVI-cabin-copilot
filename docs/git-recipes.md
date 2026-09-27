# Sổ tay Git — các tình huống đã gặp thật và cách xử lý

Ghi lại từ phiên làm việc 2026-08-12 (chuỗi PR #75 → #81 → #68 → #70). Mỗi mục là một
tình huống **đã xảy ra**, không phải lý thuyết. Bổ sung cho `docs/GIT_WORKFLOW.md` —
file kia nói quy trình chuẩn, file này nói lúc quy trình gãy thì làm gì.

Nguyên tắc xuyên suốt: **chẩn đoán trước, đừng sửa mù**. Mọi lỗi git dưới đây đều có một
lệnh chỉ-đọc cho biết chính xác chuyện gì đang xảy ra, và lệnh đó luôn rẻ hơn việc đoán sai.

---

## 0. Bộ lệnh chẩn đoán — chạy trước khi làm bất cứ gì

```
git branch --show-current
```
```
git status --porcelain
```
```
git log --oneline -3
```

Ba lệnh này trả lời: *tôi đang đứng ở đâu, cây có sạch không, HEAD ở đâu*. Phần lớn sự cố
trong phiên vừa rồi bắt nguồn từ việc bỏ qua một trong ba.

So sánh local với remote:

```
git fetch origin
```
```
git log --oneline HEAD..origin/<nhánh>
```
```
git log --oneline origin/<nhánh>..HEAD
```

Hai lệnh cuối đọc là: *remote có gì mà tôi không có* và *tôi có gì mà remote không có*.
**Cả hai rỗng = khớp hoàn toàn.** Chỉ cái trên có nội dung = mình chậm hơn. Chỉ cái dưới
có = mình đi trước, push được. Cả hai đều có = đã rẽ nhánh, phải hoà.

---

## 1. Tạo nhánh mới đúng chỗ

```
git checkout develop
```
```
git pull origin develop
```
```
git checkout -b fix/<mô-tả-ngắn>
```

**Vì sao `pull` ở giữa:** `git checkout -b` tạo nhánh từ **HEAD hiện tại**, không phải từ
remote. Bỏ qua `pull` là nhánh mới sinh ra đã lạc hậu, và bạn sẽ phải hoà develop ngay sau đó.

**Bẫy:** thay đổi chưa commit sẽ **đi theo** bạn khi `checkout` sang nhánh khác. Đôi khi
tiện, đôi khi khiến bạn commit nhầm nhánh. Kiểm `git status` trước.

---

## 2. Gộp nhiều commit thành một (squash) mà không cần rebase tương tác

Tình huống: một nhánh có 2 commit trùng hệt tên nhau, muốn gộp lại trước khi người khác review.

```
git reset --soft HEAD~2
```
```
git commit -m "<một message duy nhất>"
```
```
git push --force-with-lease origin <nhánh>
```

**Vì sao `--soft`:** nó **chỉ di chuyển con trỏ nhánh**, không đụng file trên đĩa. Toàn bộ
thay đổi của 2 commit nằm lại trong staging area, sẵn sàng commit lại thành một.
(`--hard` sẽ xoá sạch — đừng nhầm.)

**Vì sao `HEAD~2` chứ không phải `origin/develop`:** hai cái có thể đang trỏ cùng chỗ, nhưng
`HEAD~2` diễn đạt đúng ý định *"gộp đúng 2 commit cuối của tôi"* và không phụ thuộc vào việc
`origin/develop` có bị dịch chuyển bởi một lần `fetch` xen vào hay không.

**Vì sao `--force-with-lease` chứ không phải `--force`:** `--force-with-lease` chỉ ghi đè nếu
remote **vẫn đang ở đúng commit mà local bạn biết**. Nếu ai đó push vào nhánh trong lúc bạn
làm, lệnh **từ chối** thay vì xoá mất công của họ. `--force` thì xoá thẳng.

**Kiểm tra trước khi chạy:**
```
git rev-parse --short HEAD~2
```
Phải ra đúng commit bạn muốn dừng lại (thường là đỉnh develop).

**Kiểm tra sau khi chạy:**
```
git diff origin/develop --stat
```
Số dòng thêm/bớt phải **giống hệt trước khi gộp**. Khác đi là có thứ gì đó rơi mất.
*(Lưu ý: tổng của 2 commit, không phải stat của riêng commit đầu — đã suýt báo động nhầm vì chuyện này.)*

---

## 3. Push bị từ chối `non-fast-forward` — "tip of your current branch is behind"

**Đừng `--force`.** Chẩn đoán trước:

```
git fetch origin
```
```
git log --oneline HEAD..origin/<nhánh>
```

Nếu remote có commit mà local không có → **nhánh local của bạn cũ hơn remote**. Nguyên nhân
thường gặp: nhánh đã tồn tại sẵn ở local từ lần trước, bạn `git checkout` rồi làm việc luôn
mà quên `git pull`.

Cách sửa:
```
git merge origin/<nhánh>
```
rồi giải conflict nếu có, commit, push.

**Bài học:** sau `git checkout <nhánh đã tồn tại>`, luôn `git pull` trước khi làm gì.

---

## 4. Push bị từ chối `fetch first` — remote đã bị viết lại (rebase/force-push)

Khác với mục 3: ở đây remote có commit **mới hoàn toàn**, thường do ai đó rebase hoặc bấm
*Update branch → Rebase* trên GitHub.

Dấu hiệu nhận biết: remote có 1 commit lạ, còn local có **nhiều** commit mà remote không có,
trong đó có cả những commit bạn **đã push thành công trước đó**.

Chẩn đoán xem có mất gì không:
```
git diff --stat <sha-cũ> <sha-mới-trên-remote>
```

Nếu diff chỉ là tiến trình của develop → nội dung không mất, chỉ đổi hình dạng lịch sử.

Chuyển các commit chưa push của bạn lên đỉnh mới:
```
git rebase --onto origin/<nhánh> <commit-cuối-cùng-đã-push>
```

Lệnh này replay **chỉ những commit sau `<commit-cuối-cùng-đã-push>`** lên trên đỉnh remote mới.
Đọc là: *"lấy các commit sau X, đặt lên trên Y"*.

**Cảnh báo quan trọng:** rebase **không làm mất code**, nhưng nó có thể **âm thầm lật ngược
một sửa đổi có chủ đích** nếu người rebase giải conflict theo hướng khác. Đã xảy ra thật:
một dòng tài liệu bị quay về giá trị cũ sai. **Sau mỗi lần lịch sử bị viết lại, kiểm nội
dung — đừng chỉ kiểm lịch sử có gọn không.**

---

## 5. Hai chiều "merge" — đừng lẫn

| | Ai làm | Ở đâu | Chiều |
|---|---|---|---|
| **Merge PR** | người có quyền merge | GitHub, nút *Merge pull request* | nhánh **→ vào** `develop` |
| **Cập nhật nhánh** | bạn | local, rồi push nhánh mình | `develop` **→ vào** nhánh |

```
git merge origin/develop
```
Lệnh này là **chiều thứ hai** — kéo develop *vào nhánh của bạn* để gỡ conflict. Nó **không**
đẩy gì lên develop. Bạn không bao giờ push thẳng vào `develop`.

---

## 6. Giải conflict — `--ours` và `--theirs` nghĩa là gì

Trong lúc `git merge`:
- `--ours` = **nhánh bạn đang đứng**
- `--theirs` = nhánh bạn đang merge vào (ví dụ `origin/develop`)

Lấy nguyên một file từ một bên:
```
git checkout --theirs -- <file>
```
```
git checkout --ours -- <file>
```

**Chỉ dùng khi một bên là tập cha của bên kia.** Cách xác định: kiểm xem bên bạn định bỏ có
thay đổi nào riêng không.

```
git show <commit-của-nhánh> --stat
```
Nếu file đang conflict **không xuất hiện** trong commit công việc của nhánh, nghĩa là nhánh
chưa từng sửa file đó → lấy nguyên bên kia, không mất gì.

Khi **cả hai bên đều có phần riêng** thì phải sửa tay: mở file, giữ cả hai, xoá 3 dòng đánh dấu
`<<<<<<<`, `=======`, `>>>>>>>`.

Kiểm sau khi giải:
```
git diff --name-only --diff-filter=U
```
Liệt kê file **chưa giải quyết**. Rỗng = xong (nhưng vẫn phải `git add`).

```
git diff --numstat <file>
```
Với file kiểu nhật ký (`WORKLOG.md`), kết quả phải là **`N 0`** — *N dòng thêm, 0 dòng xoá*.
Có số xoá nghĩa là bạn vừa đè mất mục của người khác. Đây cũng là cách phát hiện line-ending
bị đổi cả file: nếu mọi dòng hiện là sửa thì bạn đã làm hỏng CRLF/LF.

Kiểm marker còn sót:
```
git grep -n "^<<<<<<<\|^>>>>>>>"
```

---

## 7. Conflict `add/add` trên file mà cả hai bên đều "thêm mới"

Nguyên nhân thường không phải hai người viết cùng file, mà là **thượng nguồn đã rebase**:
develop nhận bản rebase (SHA mới), nhánh của bạn vẫn mang bản gốc (SHA cũ) — **cùng nội dung,
khác danh tính**, nên git coi như hai file khác nhau cùng được thêm.

Xác nhận:
```
git diff --stat <sha-cũ> <sha-mới> -- <file đang conflict>
```

**Rỗng = cùng nội dung** → đây là chuyện danh tính, không phải chuyện nội dung. Cách giải:
chọn bên có nhiều sửa đổi hơn, không cần đọc từng dòng.

---

## 8. Kiểm trước khi nhờ merge — không cần merge thử

```
git merge-tree --write-tree --name-only origin/develop <nhánh>
```

Trả về danh sách file sẽ conflict, **không đụng gì tới cây làm việc hay nhánh**. Dùng để trả
lời "PR này merge được chưa" mà không phải thật sự merge.

Đo độ lạc hậu:
```
git rev-list --count <nhánh>..origin/develop
```
Số commit của develop mà nhánh chưa có.

Kiểm quan hệ cha–con giữa hai commit/nhánh:
```
git merge-base --is-ancestor <A> <B>
```
Không in gì, chỉ trả exit code. Dùng để hỏi *"#68 đã vào develop chưa"*, hoặc phát hiện
**PR này có chứa trọn PR kia không** — nếu có thì merge PR này trước là kéo luôn PR kia vào
mà chưa ai review nó.

---

## 9. Lỡ tay — đường lùi

```
git reflog -10
```

Ghi lại **mọi** lần HEAD dịch chuyển, kể cả commit đã bị `reset` bỏ đi. Lấy SHA từ đây rồi:

```
git reset --hard <sha>
```

Đưa mọi thứ về đúng trạng thái đó. Nếu đã push rồi thì làm tiếp `--force-with-lease`.

**Thói quen tốt:** trước khi chạy lệnh viết lại lịch sử, ghi lại SHA hiện tại:
```
git rev-parse HEAD
```

---

## 10. Những cái bẫy đã vấp trong phiên này

**`.gitignore` với pattern kết thúc bằng `/`** chỉ khớp **đúng** thư mục đó. `.venv/` **không**
khớp `.venv311/`. Tạo venv mới tên khác là 1.2 GB lọt vào `git status`. Sửa: `.venv*/`.
`.dockerignore` có cùng lỗi và hậu quả nặng hơn — build context phình, `docker build` treo.

**`git add .` khi có thư mục lớn chưa được ignore.** Trong phiên này luôn add từng file cụ thể
vì `.venv311/` đang untracked. Rẻ hơn nhiều so với việc gỡ một commit 1.2 GB.

**`core.autocrlf = true`** (mặc định trên Windows): git tự chuẩn hoá CRLF↔LF khi commit, nên
ghi file bằng LF không gây hại. Cảnh báo *"LF will be replaced by CRLF"* là bình thường. Nhưng
nếu bạn dùng công cụ ngoài để sửa file, hãy kiểm `git diff --numstat` — số xoá bằng số dòng cả
file nghĩa là line-ending đã bị đổi hàng loạt.

**Commit merge không mất công viết message.** `git commit --no-edit` dùng message mặc định.
Nhưng nếu bạn có **quyết định** khi giải conflict, hãy viết ra:
```
git commit -m "merge: <nguồn> vào <đích>, giải conflict <file>" -m "<lý do chọn bên nào và vì sao>"
```
Người review sau này không có cách nào đoán được bạn đã cân nhắc gì.

**Nhánh có tồn tại ở local không đồng nghĩa nó cập nhật.** `git branch -a` liệt kê cả nhánh
local cũ. Đây là nguyên nhân của mục 3.
