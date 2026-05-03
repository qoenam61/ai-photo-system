# Phase 0-LLM 벤치마크 결과

- **모델**: qwen2.5vl:7b
- **벤치마크 자산**: 198 장
- **유효**: 194 / 오류 4

## 종합 정확도

- **정확도**: **31.4%** (61/194)
- **합격 기준 (80%)**: ❌ FAIL

## 처리 시간 (ms)

- 평균: 32104 / 중앙값: 26550 / p95: 54031
- 합격 기준 (1장 ≤ 6000ms): ❌ FAIL

## 등급별 정확도

| 등급 | 자산 | 정확 | 정확도 |
|---|---|---|---|
| EVENT | 57 | 4 | 7.0% |
| BEST | 37 | 6 | 16.2% |
| FOOD | 17 | 16 | 94.1% |
| MEMORY+ | 37 | 31 | 83.8% |
| MEMORY- | 14 | 0 | 0.0% |
| NORMAL | 15 | 1 | 6.7% |
| TRASH | 17 | 3 | 17.6% |

## Confusion Matrix (사용자 라벨 → AI 예측 분포)


### EVENT (57 장)
  - BEST: 42
  - MEMORY+: 10
  - EVENT: 4 ✓
  - MEMORY-: 1

### BEST (37 장)
  - MEMORY+: 30
  - BEST: 6 ✓
  - NORMAL: 1

### FOOD (17 장)
  - FOOD: 16 ✓
  - NORMAL: 1

### MEMORY+ (37 장)
  - MEMORY+: 31 ✓
  - BEST: 6

### MEMORY- (14 장)
  - MEMORY+: 10
  - BEST: 3
  - NORMAL: 1

### NORMAL (15 장)
  - MEMORY+: 13
  - NORMAL: 1 ✓
  - BEST: 1

### TRASH (17 장)
  - NORMAL: 7
  - TRASH: 3 ✓
  - MEMORY-: 3
  - FOOD: 2
  - MEMORY+: 1
  - BEST: 1

## 재분류 후보 (133 장)

AI 예측이 사용자 라벨과 다름 — 검토하시고 폴더 이동 또는 그대로 유지 결정.

| # | 파일 | 사용자 | AI | 신뢰도 | AI 사유 |
|---|---|---|---|---|---|
| 1 | `IMG_5464.jpeg` | **TRASH** | **FOOD** | 10 | 화면에 음식이 50% 이상 차지되어 있습니다. |
| 2 | `IMG_7581.jpeg` | **TRASH** | **FOOD** | 10 | 음식이 화면 50% 이상 차지하여 FOOD 등급에 해당합니다. |
| 3 | `IMG_0087.JPG` | **EVENT** | **BEST** | 9 | 사진에 두 사람이 등장하고, 화질이 양호하며, 인물이 주요 주제로 나와 있어 '자랑 가능'한 인생샷으로 분류됩니다. |
| 4 | `IMG_0088.JPG` | **EVENT** | **BEST** | 9 | 사진에는 3명의 사람이 있으며, 화질이 양호하고, 인물들이 주를 이루고 있어 BEST에 해당합니다. |
| 5 | `IMG_0089.JPG` | **EVENT** | **BEST** | 9 | 인물이 두 명이고, 웨딩 드레스를 입고 있으며, 화질이 양호하여 자랑할 만한 인생샷입니다. |
| 6 | `IMG_0640.jpeg` | **EVENT** | **BEST** | 9 | 인물이 주요 주체이며, 웨딩 드레스와 꽃다발이 있어 BEST에 해당합니다. |
| 7 | `IMG_0680.jpeg` | **EVENT** | **BEST** | 9 | 인물이 주요 주제이며, 잘 나온 인생샷으로 자랑 가능 |
| 8 | `IMG_0704.jpeg` | **EVENT** | **BEST** | 9 | 사람 2명이 있고, 풍경이 아닌 주제가 인물이므로 BEST에 해당하며, 인물이 잘 나와서 자랑 가능하다는 점에서 BEST로 분류됩니다. |
| 9 | `IMG_1138.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 10 | `IMG_1834.JPG` | **EVENT** | **MEMORY+** | 9 | 사람 2명 + 화질 양호 + 일상 |
| 11 | `IMG_2476.JPG` | **EVENT** | **BEST** | 9 | 사진에는 두 명의 사람이 있으며, 화질이 양호하고, 흥미로운 테마인 할로윈이 반영되어 있어 자랑할 만한 인생샷으로 분류됩니다. |
| 12 | `IMG_2477.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로, 가족과 함께 재미있는 의상을 착용하고 즐거운 표정을 짓고 있습니다. |
| 13 | `IMG_3091.JPG` | **EVENT** | **BEST** | 9 | 인물이 주요 주제이며, 화질이 양호하고, 인생샷으로 자랑 가능합니다. |
| 14 | `IMG_5925.JPG` | **EVENT** | **BEST** | 9 | 사진에는 두 사람이 있고, 한 명은 임신 중인 듯한 옷차림을 하고 있으며, 다른 한 명은 강아지를 안고 있다. 이는 '자랑 가능'한 순간을 담은 |
| 15 | `IMG_5927.JPG` | **EVENT** | **MEMORY+** | 9 | 사람 2명 + 화질 양호 + 일상 |
| 16 | `IMG_5930.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 17 | `IMG_6353.jpeg` | **EVENT** | **BEST** | 9 | 사진은 흐림이 없고, 인물이 주요 주체로, 인생샷으로 자랑 가능. |
| 18 | `IMG_6504.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 웨딩 사진 |
| 19 | `IMG_6544.JPG` | **EVENT** | **BEST** | 9 | 사진에는 두 명의 사람이 있으며, 한복을 입고 있으며, 화질이 양호하고, 인생샷으로 자랑 가능합니다. |
| 20 | `IMG_6545.JPG` | **EVENT** | **BEST** | 9 | 사진에는 웨딩 드레스와 꽃다발이 있으며, 인물들이 잘 포즈를 취하고 있어 자랑 가능함. |
| 21 | `IMG_6699.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 22 | `IMG_6702.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 23 | `IMG_6717.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 24 | `IMG_6720.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 25 | `IMG_6947.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로, 두 사람이 화면 중심에 있으며, 웨딩 드레스와 한복을 착용하고 있어 BEST에 해당합니다. |
| 26 | `IMG_6962.JPG` | **EVENT** | **BEST** | 9 | 사진에는 3명의 사람이 있으며, 중앙에 위치한 사람은 웨딩 드레스를 입고 있으며, 양쪽에는 한복을 입은 두 명의 사람이 앉아 있다. 이는 결혼식 |
| 27 | `IMG_7108.jpeg` | **EVENT** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 28 | `IMG_7132.JPG` | **EVENT** | **BEST** | 9 | 사진에 두 사람이 있으며, 웨딩 드레스와 정장이 보여서 이벤트로 분류되며, '자랑 가능' 조건을 만족하여 BEST로 분류됩니다. |
| 29 | `IMG_7135.JPG` | **EVENT** | **BEST** | 9 | 사진에 두 사람이 한복을 입고 있으며, 인생샷으로 자랑할 만한 모습이다. |
| 30 | `IMG_7137.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로 보이며, 졸업식을 기념하는 분위기 |
| 31 | `IMG_7378.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 가족 사진, 인물이 주요 주제 |
| 32 | `IMG_7468.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 33 | `IMG_7495.jpeg` | **EVENT** | **BEST** | 9 | 사진에 두 사람이 있으며, 웨딩 드레스와 정장을 착용하고 있어 기념일 분위기가 느껴지며, 인생샷으로 자랑할 만한 사진이다. |
| 34 | `IMG_7504.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로, 사람들이 주로 나와 있고, 화질도 양호하여 BEST에 해당합니다. |
| 35 | `IMG_7524.JPG` | **EVENT** | **BEST** | 9 | 사진에는 3명의 사람과 함께 있으며, 인물들이 잘 포즈를 취하고 있어 자랑할 만한 인생샷으로 분류됩니다. |
| 36 | `IMG_7536.JPG` | **EVENT** | **BEST** | 9 | 사진에는 사람이 주로 보이지 않으며, 주요 주제는 강아지로, 강아지가 잘 나온 인생샷으로 자랑 가능하다. |
| 37 | `IMG_7552.JPG` | **EVENT** | **BEST** | 9 | 사진에는 웨딩 드레스를 입은 사람이 있고, 이는 BEST의 기준을 충족합니다. |
| 38 | `IMG_7590.JPG` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 39 | `IMG_7764.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로, 텍스트가 포함되어 있어 특별한 의미가 있다. |
| 40 | `IMG_7766.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로, 50일을 기념하는 사진이자, 주인공이 명확하게 보여서 BEST에 속함 |
| 41 | `IMG_7776.jpeg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 42 | `_talkf_wzAd88JPOT_JYmrSKiHgMBg4PfKL8TlU0_f_8f0ac19bbf6a.jpg` | **EVENT** | **BEST** | 9 | 자랑 가능한 가족사진, 인물이 주요 주제 |
| 43 | `beauty_1649654117040.JPEG` | **EVENT** | **BEST** | 9 | 사람 3명이 포함되어 있고, 풍경이나 사물이 주는 것이 아니라 사람들이 주는 사진이므로 BEST에 해당합니다. |
| 44 | `beauty_1649654136130.JPEG` | **EVENT** | **BEST** | 9 | 사람 3명이 있고, 품종이 다른 두 개의 개가 있으며, 인생샷으로 보이는 특별한 분위기 |
| 45 | `beauty_1663595334871.JPEG` | **EVENT** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 46 | `https___kids-i.kakaocdn.net_dn_Rw4id_btsSn8dNygZ_qzJ64h2sdKL7VKz7aZFfj1_img.jpg` | **EVENT** | **BEST** | 9 | 사람 1명 + 흐림/어두움/구도 어색이 아니고, 잘 나온 인생샷으로 자랑 가능 |
| 47 | `https___kids-i.kakaocdn.net_dn_c2Mp3U_btsSrjsdQq0_fOKsPTZxz4k2lBRky1hjqk_img.jpg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷으로, 많은 사람들이 모여 있고, 크리스마스 분위기가 느껴지며, 인물들이 화면의 주요 요소로 보입니다. |
| 48 | `https___kids-i.kakaocdn.net_dn_f4X2J_btsRO68ILUb_tGDUvpxaM4Rlgqyroo29Kk_img.jpg` | **EVENT** | **BEST** | 9 | 자랑 가능한 인생샷, 사람들이 주요 인물이고 화질이 양호하여 BEST에 속함 |
| 49 | `https___kids-i.kakaocdn.net_dn_vPSlc_btsQshjfoiy_gJf1diZYBfZ9zhofSMnsa1_img.jpg` | **EVENT** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 50 | `https___kids-i.kakaocdn.net_dn_vhbGb_btsRUCU8TzV_aZgvC5OlRt99AZZXif0Gi1_img.jpg` | **EVENT** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 활동 |
| 51 | `IMG_1179.JPG` | **BEST** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 52 | `IMG_5572.jpeg` | **BEST** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 53 | `IMG_6061.jpeg` | **BEST** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 54 | `IMG_6764.jpeg` | **BEST** | **MEMORY+** | 9 | 사람 2명 + 화질 양호 + 일상 |
| 55 | `IMG_6765.jpeg` | **BEST** | **MEMORY+** | 9 | 사람 1~2명 + 화질 양호 + 일상 |
| 56 | `IMG_7112.JPG` | **BEST** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 57 | `IMG_7374.JPG` | **BEST** | **MEMORY+** | 9 | 사람 3명이 포함되어 있고, 화질이 양호하며 일상적인 가족 사진으로 보입니다. |
| 58 | `https___kids-i.kakaocdn.net_dn_bvlKTU_btsRj5oEHnE_Y0JmbadG0QNtFk7JBL1aOK_img.jpg` | **BEST** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 59 | `https___kids-i.kakaocdn.net_dn_hud6b_btsRIKycA7o_RPCLQyLzjZMvKaiuH7cVm1_img.jpg` | **BEST** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 60 | `IMG_4074.jpeg` | **MEMORY+** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 61 | `IMG_4530.jpeg` | **MEMORY+** | **BEST** | 9 | 사진에는 두 명의 사람과 한 명의 어린이가 있으며, 인물들이 주를 이루고 있으며, 화질도 양호하여 자랑할 만한 인생샷으로 분류됩니다. |
| 62 | `IMG_5567.jpeg` | **MEMORY+** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 63 | `IMG_7021.jpeg` | **MEMORY+** | **BEST** | 9 | 자랑 가능한 인생샷으로 보여집니다. |
| 64 | `IMG_7111.JPG` | **MEMORY+** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 65 | `IMG_7519.JPG` | **MEMORY+** | **BEST** | 9 | 사진에는 3명의 사람이 있으며, 인물들이 잘 포즈를 취하고 있어 자랑할 만한 사진으로 보입니다. |
| 66 | `IMG_0707.jpeg` | **MEMORY-** | **BEST** | 9 | 사진에는 두 명의 사람이 있으며, 한 명이 다른 한 명을 향해 손을 잡고 있는 모습이 보이며, 이는 '자랑 가능'한 인생샷으로 분류됩니다. |
| 67 | `IMG_4476.jpeg` | **MEMORY-** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 68 | `IMG_4529.jpeg` | **MEMORY-** | **BEST** | 9 | 사진에는 두 명의 사람과 큰 로봇 조형물이 있으며, 인생샷으로 보이는 특성이 있어 BEST 등급에 속함. |
| 69 | `https___kids-i.kakaocdn.net_dn_cWn3PT_btsSsUuazRP_M7KhdhjK9HOQzxDVm5RDL0_img.jpg` | **MEMORY-** | **MEMORY+** | 9 | 사람 1~2명 + 화질 양호 + 일상 |
| 70 | `https___kids-i.kakaocdn.net_dn_kQxBK_btsSCmoIBuY_mkDmh8d5hgGRpsoakmuajk_img.jpg` | **MEMORY-** | **MEMORY+** | 9 | 사람 2명 + 화질 양호 + 일상 |
| 71 | `https___kids-i.kakaocdn.net_dn_LDQ00_btsRYFCJP1L_8gNsanPdw5FK4LDBiE0V00_img.jpg` | **NORMAL** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 활동 |
| 72 | `https___kids-i.kakaocdn.net_dn_bCazmi_btsR6Za579A_0FlweVxeoJYYJlNK0TcY30_img.jpg` | **NORMAL** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 73 | `https___kids-i.kakaocdn.net_dn_d5uC9M_btsR81LZCVu_kvM69znmPKXh6rvIU9FY2k_img.jpg` | **NORMAL** | **MEMORY+** | 9 | 사람 3명이 등장하고, 화질이 양호하며 일상적인 장면을 담고 있습니다. |
| 74 | `https___kids-i.kakaocdn.net_dn_izNtH_btsRo8TBnam_3NwTrHh7lZ7kM2a91BLGn1_img.jpg` | **NORMAL** | **MEMORY+** | 9 | 사람 1명 + 화질 양호 + 일상 |
| 75 | `https___kids-i.kakaocdn.net_dn_mLM47_btsSGKcaBO7_Vc85Hr8FrX97X75h92pN5k_img.jpg` | **NORMAL** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 76 | `IMG_7041.jpeg` | **TRASH** | **BEST** | 9 | 자랑 가능한 인생샷 |
| 77 | `IMG_7324.JPG` | **EVENT** | **MEMORY+** | 8 | 사람 1명 + 풍경/사물이 主이므로 MEMORY+ 분류 |
| 78 | `IMG_7379.JPG` | **EVENT** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 79 | `IMG_7427.jpeg` | **EVENT** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 80 | `https___kids-i.kakaocdn.net_dn_dDsMO4_btsRXaI3VQg_5gakgSxrJ42d2wH3Vbtha0_img.jpg` | **EVENT** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 활동 |
| 81 | `IMG_0062.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 82 | `IMG_0068.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 83 | `IMG_0860.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 84 | `IMG_3504.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 85 | `IMG_5413.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 86 | `IMG_5422.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 87 | `IMG_5435.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 88 | `IMG_5447.JPG` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 89 | `IMG_5569.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 90 | `IMG_5608.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 91 | `IMG_5612.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 92 | `IMG_5613.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 93 | `IMG_5866.JPG` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 94 | `IMG_5998.JPG` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 95 | `IMG_6024.JPG` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 96 | `IMG_6025.JPG` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 97 | `IMG_6264.jpeg` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 98 | `IMG_8456.JPG` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 99 | `IMG_8462.JPG` | **BEST** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 100 | `beauty_1656122527884.JPEG` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 101 | `beauty_1656137875948.JPEG` | **BEST** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 102 | `IMG_0122.JPG` | **MEMORY-** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 103 | `IMG_0716.JPG` | **MEMORY-** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 104 | `IMG_2386.jpeg` | **MEMORY-** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 활동 |
| 105 | `IMG_2661.jpeg` | **MEMORY-** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 106 | `IMG_4473.jpeg` | **MEMORY-** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 107 | `IMG_5417.jpeg` | **MEMORY-** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 108 | `IMG_5585.jpeg` | **MEMORY-** | **NORMAL** | 8 | 사람이 화면의 30% 미만으로, 주요 요소는 풍경과 사물이므로 NORMAL |
| 109 | `IMG_5591.jpeg` | **MEMORY-** | **MEMORY+** | 8 | 사람 1~2명 + 화질 양호 + 일상 |
| 110 | `IMG_7030.jpeg` | **MEMORY-** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 111 | `IMG_4072.jpeg` | **NORMAL** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 112 | `IMG_5536.jpeg` | **NORMAL** | **MEMORY+** | 8 | 사람 1~2명 + 화질 양호 + 일상 |
| 113 | `https___kids-i.kakaocdn.net_dn_bUqb5z_btsQW2d2IFs_gkGjCgyZthcS0ohf3sf7Ck_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 활동 |
| 114 | `https___kids-i.kakaocdn.net_dn_bbOCld_btsRofxP982_QvbwSHRdHu3QVWEzr8tIN0_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 활동 |
| 115 | `https___kids-i.kakaocdn.net_dn_dkwK6x_btsR0VlS6IJ_1CHaDybN3AUsL6m3x9Ghk0_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 116 | `https___kids-i.kakaocdn.net_dn_ehl65X_btsRIRqmIvQ_yqv0iKOB6dlBKE6Y5PHpY0_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 1명 + 일상 활동 + 화질 양호 |
| 117 | `https___kids-i.kakaocdn.net_dn_vMXsY_btsRJRwE4nZ_7FvPCVOqhRiwn6jjKc5Jf0_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 1~2명 + 화질 양호 + 일상 |
| 118 | `https___up-kids-kage.kakao.com_dn_7xxKE_dJMcac3JDGM_HnmHwUWI5BWjfECfm0Kwkk_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 119 | `https___up-kids-kage.kakao.com_dn_BpH0l_dJMcacCRJaV_S5LJ1EtaEQKAXwiwgBrNy1_img.jpg` | **NORMAL** | **MEMORY+** | 8 | 사람 2명 + 화질 양호 + 일상 |
| 120 | `IMG_0166.HEIC` | **TRASH** | **NORMAL** | 8 | 사람이 화면에 주로 등장하지 않으며, 반려동물이 주요 주제입니다. |
| 121 | `IMG_0217.jpeg` | **TRASH** | **MEMORY+** | 8 | 사람 1명 + 화질 양호 + 일상 |
| 122 | `IMG_0228.JPG` | **TRASH** | **NORMAL** | 8 | 사람이 화면의 30% 미만으로, 주요 요소는 풍경/사물이므로 NORMAL |
| 123 | `IMG_5529.jpeg` | **TRASH** | **NORMAL** | 8 | 사람이 화면에 나타나지 않으며, 주요 요소는 풍경과 사물이므로 NORMAL 분류. |
| 124 | `IMG_5958.jpeg` | **TRASH** | **NORMAL** | 8 | 사람이 화면에 나타나지 않으며, 주요 요소는 실내 가구와 장식물로 구성되어 있습니다. |
| 125 | `IMG_7245.jpeg` | **EVENT** | **MEMORY-** | 7 | 사람이 화면의 30% 미만으로 보이며, 흐림이 있어 MEMORY-로 분류됩니다. |
| 126 | `IMG_6316.jpeg` | **BEST** | **NORMAL** | 7 | 사람이 화면의 30% 미만으로, 풍경이 주제가 되어 있습니다. |
| 127 | `IMG_5981.jpeg` | **FOOD** | **NORMAL** | 7 | 사람이 없고, 주요 요소는 음식과 식사 장면으로 일상적인 분위기 |
| 128 | `IMG_0218.jpeg` | **TRASH** | **MEMORY-** | 7 | 사람이 화면의 30% 미만으로, 풍경이 주제가 되어 있어 NORMAL에 해당하지만, 흐림이 있어 MEMORY-로 분류됩니다. |
| 129 | `IMG_6773.jpeg` | **TRASH** | **NORMAL** | 7 | 사람이 화면의 30% 미만으로, 주로 풍경/사물이 주를 이루고 있다. |
| 130 | `IMG_7119.jpeg` | **TRASH** | **NORMAL** | 7 | 사람이 화면의 30% 미만으로, 주요 요소는 풍경/사물이므로 NORMAL |
| 131 | `IMG_7322.jpeg` | **TRASH** | **MEMORY-** | 7 | 사람이 1명이고 흐림이 있고 어두운 분위기 |
| 132 | `IMG_7483.jpeg` | **TRASH** | **MEMORY-** | 7 | 사람이 화면 30% 미만으로, 흐림이 있고 어두운 분위기로 인해 MEMORY-로 분류됩니다. |
| 133 | `IMG_7575.jpeg` | **TRASH** | **NORMAL** | 7 | 사람이 없고, 주요 요소는 식물과 실내 장식품으로 구성되어 있습니다. |
