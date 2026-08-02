/**
 * survey_data.js — 10 步问卷配置
 * 每步分组定义所有 236 题的字段、类型、选项、验证规则
 * 与 questionnaire_parser.py 的 PHYSICS_FIELD_MAP 对齐
 */
window.SURVEY_STEPS = [
  // ───── 第 1 步：个人信息 ─────
  {
    icon: '📋', title: '个人信息', desc: '我们先认识一下你',
    groups: [{
      title: '基本资料',
      questions: [
        { id: 'q1_name', type: 'text', label: '你的称呼（可使用昵称）', required: true, ph: '请使用昵称或代号' },
        { id: 'q2_gender', type: 'radio', label: '性别', required: true,
          opts: [{v:'男',l:'男'},{v:'女',l:'女'}] },
        { id: 'q3_birth', type: 'date', label: '出生日期', required: true, hint: '用于年龄计算' },
        { id: 'q4_ethnicity', type: 'select', label: '民族', required: true,
          opts: '56个民族列表', optsInline: [
            {v:'汉族',l:'汉族'},{v:'壮族',l:'壮族'},{v:'回族',l:'回族'},{v:'苗族',l:'苗族'},
            {v:'满族',l:'满族'},{v:'彝族',l:'彝族'},{v:'土家族',l:'土家族'},{v:'藏族',l:'藏族'},
            {v:'蒙古族',l:'蒙古族'},{v:'其他',l:'其他'},
          ]},
        { id: 'q5_exam_id', type: 'text', label: '本地标识码（选填，请勿填真实考生号）', ph: '可留空；如需区分记录可填代号' },
        { id: 'q6_phone', type: 'text', label: '手机号（选填，本地推荐不需要）', ph: '可留空；本项目不发送通知' },
        { id: 'q8b_student_type', type: 'radio', label: '考生类型', required: true,
          opts: [{v:'应届',l:'应届'},{v:'复读',l:'复读'}] },
        { id: 'q8c_political_status', type: 'radio', label: '政治面貌',
          opts: [{v:'中共党员',l:'中共党员'},{v:'共青团员',l:'共青团员'},{v:'群众',l:'群众'}] },
        { id: 'q7_parent_name', type: 'text', label: '家长称呼（可使用昵称）', ph: '选填' },
        { id: 'q8_parent_phone', type: 'text', label: '家长电话（选填）', ph: '可留空；本项目不发送通知' },
      ]
    }]
  },

  // ───── 第 2 步：健康状况 ─────
  {
    icon: '🏥', title: '身体状况', desc: '体检信息用于专业限制过滤',
    groups: [{
      title: '体格检查',
      questions: [
        { id: 'q9_color_vision', type: 'radio', label: '色觉', required: true,
          opts: [{v:'正常',l:'正常'},{v:'色弱',l:'色弱'},{v:'色盲',l:'色盲'},{v:'颜色识别障碍',l:'颜色识别障碍'}] },
        { id: 'q10_vision', type: 'radio', label: '视力情况', required: true,
          opts: [
            {v:'视力正常',l:'视力正常'},{v:'近视但矫正后达标',l:'近视但矫正后达标'},
            {v:'裸眼视力不足5.0',l:'裸眼视力<5.0'},{v:'裸眼视力不足4.8',l:'裸眼视力<4.8'},
          ]},
        { id: 'q11_hearing', type: 'radio', label: '听力', required: true,
          opts: [{v:'听力正常',l:'听力正常'},{v:'听力障碍',l:'听力障碍'}] },
        { id: 'q11b_smell', type: 'radio', label: '嗅觉', required: true,
          opts: [{v:'嗅觉正常',l:'嗅觉正常'},{v:'嗅觉迟钝',l:'嗅觉迟钝'}] },
        { id: 'q11c_height', type: 'number', label: '身高（cm）', hint: '警校/军校报考需要', ph: '如 175' },
        { id: 'q11d_weight', type: 'number', label: '体重（kg）', hint: '同身高搭配用于BMI计算', ph: '如 65' },
        { id: 'q11e_tattoo', type: 'radio', label: '纹身/疤痕', hint: '警校/军校可能受限',
          opts: [{v:'无',l:'无'},{v:'有',l:'有'}] },
      ]
    }]
  },

  // ───── 第 3 步：高考成绩 —— 最快！⚡ ─────
  {
    icon: '📊', title: '高考成绩', desc: '核心数据，填完我们就有了大部分推荐依据 ⚡',
    groups: [{
      title: '高考分数',
      questions: [
        { id: 'q12_total_score', type: 'big-number', label: '高考总分', required: true,
          hint: '裸分（不含加分），满分 750', ph: '580' },
        { id: 'q13_rank', type: 'big-number', label: '全省位次', required: true,
          hint: '成绩单上的位次号（核心字段）', ph: '15000' },
        { id: 'q14_category', type: 'radio', label: '科类', required: true,
          hint: '选物理的还是历史的？',
          opts: [{v:'物理类',l:'🧪 物理类'},{v:'历史类',l:'📜 历史类'}] },
        { id: 'q15_subject_combo', type: 'radio', label: '选科组合', required: true,
          hint: '你的 3 门选考科目',
          opts: [
            {v:'物理+化学+生物',l:'物化生'},{v:'物理+化学+地理',l:'物化地'},
            {v:'物理+化学+政治',l:'物化政'},{v:'物理+生物+地理',l:'物生地'},
            {v:'物理+生物+政治',l:'物生政'},{v:'历史+政治+地理',l:'历政地'},
            {v:'历史+政治+生物',l:'历政生'},{v:'历史+地理+生物',l:'历地生'},
          ]},
        { id: 'q16_foreign_language', type: 'radio', label: '外语语种', required: true,
          opts: [{v:'英语',l:'英语'},{v:'日语',l:'日语'},{v:'俄语',l:'俄语'},{v:'其他',l:'其他'}] },
      ]
    }]
  },

  // ───── 第 4 步：学科能力（按科类分支） ─────
  {
    icon: '🧠', title: '学科能力', desc: '各科强弱项，帮我们判断专业适配度',
    groups: [{
      title: '语数英成绩',
      questions: [
        { id: 'q17_chinese_score', type: 'number', label: '语文分数', ph: '如 120' },
        { id: 'q22_math_score', type: 'number', label: '数学分数', ph: '如 140' },
        { id: 'q27_english_score', type: 'number', label: '英语分数', ph: '如 130' },
      ]
    },{
      title: '选考科目成绩（物理类）',
      condition: cat => cat === '物理类',
      questions: [
        { id: 'q51_physics_achievement', type: 'radio', label: '物理学科掌握程度',
          opts: [{v:'物理很好',l:'很好（排名靠前）'},{v:'物理较好',l:'较好（中上）'},{v:'物理一般',l:'一般（中等）'},{v:'物理较弱',l:'较弱（吃力）'}] },
        { id: 'q52_physics_willingness', type: 'radio', label: '大学是否愿意继续学物理相关',
          opts: [{v:'非常愿意',l:'非常愿意'},{v:'愿意',l:'愿意'},{v:'无所谓',l:'无所谓'},{v:'不愿意',l:'不愿意'}] },
        { id: 'q53_chemistry_achievement', type: 'radio', label: '化学学科掌握程度',
          opts: [{v:'化学很好',l:'很好（排名靠前）'},{v:'化学较好',l:'较好（中上）'},{v:'化学一般',l:'一般（中等）'},{v:'化学较弱',l:'较弱（吃力）'}] },
        { id: 'q54_chemistry_willingness', type: 'radio', label: '大学是否愿意继续学化学相关',
          opts: [{v:'非常愿意',l:'非常愿意'},{v:'愿意',l:'愿意'},{v:'无所谓',l:'无所谓'},{v:'不愿意',l:'不愿意'}] },
        { id: 'q55_physics_direction', type: 'radio', label: '物理方向偏好',
          opts: [{v:'偏理论',l:'偏理论/基础研究'},{v:'偏应用',l:'偏应用/工程技术'},{v:'不确定',l:'不确定'}] },
      ]
    },{
      title: '选考科目成绩（历史类）',
      condition: cat => cat === '历史类',
      questions: [
        { id: 'q32_history_score', type: 'number', label: '历史分数', ph: '如 85' },
        { id: 'q53_history_achievement', type: 'radio', label: '历史学科掌握程度',
          opts: [{v:'历史很好',l:'很好（排名靠前）'},{v:'历史较好',l:'较好（中上）'},{v:'历史一般',l:'一般（中等）'},{v:'历史较弱',l:'较弱（吃力）'}] },
        { id: 'q54_history_willingness', type: 'radio', label: '大学是否愿意继续学历史相关',
          opts: [{v:'非常愿意',l:'非常愿意'},{v:'愿意',l:'愿意'},{v:'无所谓',l:'无所谓'},{v:'不愿意',l:'不愿意'}] },
        { id: 'q33_politics_score', type: 'number', label: '政治分数', ph: '如 82' },
        { id: 'q55_foreign_language_achievement', type: 'radio', label: '外语学科掌握程度',
          opts: [{v:'外语很好',l:'很好（排名靠前）'},{v:'外语较好',l:'较好（中上）'},{v:'外语一般',l:'一般（中等）'},{v:'外语较弱',l:'较弱（吃力）'}] },
        { id: 'q56_foreign_language_willingness', type: 'radio', label: '大学是否愿意继续学外语相关',
          opts: [{v:'非常愿意',l:'非常愿意'},{v:'愿意',l:'愿意'},{v:'无所谓',l:'无所谓'},{v:'不愿意',l:'不愿意'}] },
        { id: 'q34_geography_score', type: 'number', label: '地理分数', ph: '如 78' },
      ]
    },{
      title: '优势学科与关注方向',
      questions: [
        { id: 'q32_advantage_1', type: 'text', label: '最有优势的科目', ph: '如 数学', condition: cat => cat === '物理类' },
        { id: 'q35_advantage_1', type: 'text', label: '最有优势的科目', ph: '如 语文', condition: cat => cat === '历史类' },
        { id: 'q33_advantage_2', type: 'text', label: '第二优势科目', ph: '如 物理', condition: cat => cat === '物理类' },
        { id: 'q36_advantage_2', type: 'text', label: '第二优势科目', ph: '如 英语', condition: cat => cat === '历史类' },
        { id: 'q34_competitions', type: 'multi-select', label: '竞赛/奖项经历', condition: cat => cat === '物理类',
          opts: [
            {v:'数学竞赛',l:'🏆 数学竞赛'},{v:'物理竞赛',l:'🏆 物理竞赛'},
            {v:'化学竞赛',l:'🏆 化学竞赛'},{v:'生物竞赛',l:'🏆 生物竞赛'},
            {v:'信息学竞赛',l:'🏆 信息学竞赛'},{v:'英语竞赛',l:'🏆 英语竞赛'},
            {v:'作文竞赛',l:'🏆 作文竞赛'},{v:'无',l:'无竞赛经历'},
          ]},
        { id: 'q37_competitions', type: 'multi-select', label: '竞赛/奖项经历', condition: cat => cat === '历史类',
          opts: [
            {v:'数学竞赛',l:'🏆 数学竞赛'},{v:'物理竞赛',l:'🏆 物理竞赛'},
            {v:'化学竞赛',l:'🏆 化学竞赛'},{v:'生物竞赛',l:'🏆 生物竞赛'},
            {v:'信息学竞赛',l:'🏆 信息学竞赛'},{v:'英语竞赛',l:'🏆 英语竞赛'},
            {v:'作文竞赛',l:'🏆 作文竞赛'},{v:'无',l:'无竞赛经历'},
          ]},
        { id: 'q35_focus_area', type: 'multi-select', label: '平时关注方向', condition: cat => cat === '物理类',
          opts: [
            {v:'科技',l:'💻 科技/互联网'},{v:'经济',l:'📈 经济/金融'},{v:'医学',l:'🏥 医学/健康'},
            {v:'教育',l:'📚 教育/文化'},{v:'工程',l:'🏗️ 工程/制造'},{v:'艺术',l:'🎨 艺术/设计'},
            {v:'法律',l:'⚖️ 法律/政策'},{v:'环境',l:'🌿 环境/农业'},
          ]},
        { id: 'q38_focus_area', type: 'multi-select', label: '平时关注方向', condition: cat => cat === '历史类',
          opts: [
            {v:'科技',l:'💻 科技/互联网'},{v:'经济',l:'📈 经济/金融'},{v:'医学',l:'🏥 医学/健康'},
            {v:'教育',l:'📚 教育/文化'},{v:'工程',l:'🏗️ 工程/制造'},{v:'艺术',l:'🎨 艺术/设计'},
            {v:'法律',l:'⚖️ 法律/政策'},{v:'环境',l:'🌿 环境/农业'},
          ]},
      ]
    }]
  },

  // ───── 第 5 步：家庭背景 ─────
  {
    icon: '👨‍👩‍👧', title: '家庭背景', desc: '预算和家庭情况帮我们做学费筛选',
    groups: [{
      title: '家庭情况',
      questions: [
        { id: 'q36_parent_education', type: 'radio', label: '父母最高学历', condition: cat => cat === '物理类',
          opts: [{v:'初中及以下',l:'初中及以下'},{v:'高中/中专',l:'高中/中专'},{v:'大专',l:'大专'},{v:'本科',l:'本科'},{v:'硕士及以上',l:'硕士及以上'}] },
        { id: 'q39_parent_education', type: 'radio', label: '父母最高学历', condition: cat => cat === '历史类',
          opts: [{v:'初中及以下',l:'初中及以下'},{v:'高中/中专',l:'高中/中专'},{v:'大专',l:'大专'},{v:'本科',l:'本科'},{v:'硕士及以上',l:'硕士及以上'}] },
        { id: 'q37_parent_occupation', type: 'radio', label: '父母职业背景', condition: cat => cat === '物理类',
          opts: [{v:'公务员/事业单位',l:'公务员/事业单位'},{v:'企业/公司',l:'企业/公司'},{v:'个体经营',l:'个体经营'},{v:'务农/务工',l:'务农/务工'},{v:'其他',l:'其他'}] },
        { id: 'q40_parent_occupation', type: 'radio', label: '父母职业背景', condition: cat => cat === '历史类',
          opts: [{v:'公务员/事业单位',l:'公务员/事业单位'},{v:'企业/公司',l:'企业/公司'},{v:'个体经营',l:'个体经营'},{v:'务农/务工',l:'务农/务工'},{v:'其他',l:'其他'}] },
        { id: 'q38_family_resources', type: 'multi-select', label: '家庭资源', condition: cat => cat === '物理类',
          opts: [{v:'教育人脉',l:'🎓 教育/学校人脉'},{v:'医疗人脉',l:'🏥 医疗/卫生人脉'},
                 {v:'企业人脉',l:'🏢 企业/行业人脉'},{v:'政府人脉',l:'🏛️ 政府/政策人脉'},
                 {v:'无特殊人脉',l:'无特殊人脉'}] },
        { id: 'q41_family_resources', type: 'multi-select', label: '家庭资源', condition: cat => cat === '历史类',
          opts: [{v:'教育人脉',l:'🎓 教育/学校人脉'},{v:'医疗人脉',l:'🏥 医疗/卫生人脉'},
                 {v:'企业人脉',l:'🏢 企业/行业人脉'},{v:'政府人脉',l:'🏛️ 政府/政策人脉'},
                 {v:'无特殊人脉',l:'无特殊人脉'}] },
        { id: 'q39_family_location', type: 'radio', label: '家庭所在地', condition: cat => cat === '物理类',
          opts: [{v:'昆明',l:'昆明'},{v:'地州城市',l:'云南地州城市'},{v:'县城',l:'县城'},{v:'乡镇/农村',l:'乡镇/农村'}] },
        { id: 'q42_family_location', type: 'radio', label: '家庭所在地', condition: cat => cat === '历史类',
          opts: [{v:'昆明',l:'昆明'},{v:'地州城市',l:'云南地州城市'},{v:'县城',l:'县城'},{v:'乡镇/农村',l:'乡镇/农村'}] },
      ]
    },{
      title: '预算与费用',
      questions: [
        { id: 'q40_total_budget', type: 'radio', label: '每年总预算（学费+生活费）', required: true, condition: cat => cat === '物理类',
          opts: [{v:'2万元以内',l:'2万元以内'},{v:'2-4万元',l:'2-4万元'},{v:'4-6万元',l:'4-6万元 (多数公办本科)'},
                 {v:'6-10万元',l:'6-10万元'},{v:'10-15万元',l:'10-15万元'},{v:'15万元以上',l:'💰 15万元以上（含中外合作）'}] },
        { id: 'q43_total_budget', type: 'radio', label: '每年总预算（学费+生活费）', required: true, condition: cat => cat === '历史类',
          opts: [{v:'2万元以内',l:'2万元以内'},{v:'2-4万元',l:'2-4万元'},{v:'4-6万元',l:'4-6万元 (多数公办本科)'},
                 {v:'6-10万元',l:'6-10万元'},{v:'10-15万元',l:'10-15万元'},{v:'15万元以上',l:'💰 15万元以上（含中外合作）'}] },
        { id: 'q40b_sino_foreign', type: 'radio', label: '是否考虑中外合作办学', condition: cat => cat === '物理类',
          opts: [{v:'是',l:'考虑'},{v:'否',l:'不考虑'},{v:'视情况',l:'视费用而定'}] },
        { id: 'q43b_sino_foreign', type: 'radio', label: '是否考虑中外合作办学', condition: cat => cat === '历史类',
          opts: [{v:'是',l:'考虑'},{v:'否',l:'不考虑'},{v:'视情况',l:'视费用而定'}] },
        { id: 'q40c_private_college', type: 'radio', label: '是否考虑民办院校', condition: cat => cat === '物理类',
          opts: [{v:'是',l:'考虑'},{v:'否',l:'不考虑'}] },
        { id: 'q43c_private_college', type: 'radio', label: '是否考虑民办院校', condition: cat => cat === '历史类',
          opts: [{v:'是',l:'考虑'},{v:'否',l:'不考虑'}] },
        { id: 'q41_political_review', type: 'radio', label: '是否计划报考政审院校', condition: cat => cat === '物理类',
          hint: '如军校、警校、北京电子科技学院等',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'不确定',l:'不确定'}] },
        { id: 'q44_political_review', type: 'radio', label: '是否计划报考政审院校', condition: cat => cat === '历史类',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'不确定',l:'不确定'}] },
        { id: 'q41a_criminal_record', type: 'radio', label: '直系亲属是否有刑事处罚记录', condition: cat => cat === '物理类',
          hint: '政审需要',
          opts: [{v:'无',l:'无'},{v:'有',l:'有'}] },
        { id: 'q44a_criminal_record', type: 'radio', label: '直系亲属是否有刑事处罚记录', condition: cat => cat === '历史类',
          opts: [{v:'无',l:'无'},{v:'有',l:'有'}] },
        { id: 'q41b_special_plan_eligibility', type: 'multi-select', label: '专项计划资格', condition: cat => cat === '物理类',
          hint: '符合条件的可以降分录取',
          opts: [{v:'国家专项',l:'🏛️ 国家专项'},{v:'高校专项',l:'🎓 高校专项'},{v:'地方专项',l:'📍 地方专项'},{v:'无',l:'无'}] },
        { id: 'q44b_special_plan_eligibility', type: 'multi-select', label: '专项计划资格', condition: cat => cat === '历史类',
          opts: [{v:'国家专项',l:'🏛️ 国家专项'},{v:'高校专项',l:'🎓 高校专项'},{v:'地方专项',l:'📍 地方专项'},{v:'无',l:'无'}] },
      ]
    }]
  },

  // ───── 第 6 步：志愿方向 ─────
  {
    icon: '🎯', title: '志愿方向', desc: '你的偏好决定我们往哪个方向推荐',
    groups: [{
      title: '核心诉求',
      questions: [
        { id: 'q42_special_schools', type: 'text', label: '是否有特别想去的院校', condition: cat => cat === '物理类', ph: '如 云南大学、昆明理工（多个用逗号隔开）' },
        { id: 'q45_special_schools', type: 'text', label: '是否有特别想去的院校', condition: cat => cat === '历史类', ph: '如 云南大学、云师大（多个用逗号隔开）' },
        { id: 'q43_core_demand', type: 'radio', label: '选学校最看重什么', required: true, condition: cat => cat === '物理类',
          opts: [{v:'专业实力优先',l:'📚 专业实力优先'},{v:'学校名气优先（985/211/双一流）',l:'🏛️ 学校名气优先'},
                 {v:'就业率优先',l:'💼 就业率优先'},{v:'考研/深造率优先',l:'🎓 考研深造优先'}] },
        { id: 'q46_core_demand', type: 'radio', label: '选学校最看重什么', required: true, condition: cat => cat === '历史类',
          opts: [{v:'专业实力优先',l:'📚 专业实力优先'},{v:'学校名气优先（985/211/双一流）',l:'🏛️ 学校名气优先'},
                 {v:'就业率优先',l:'💼 就业率优先'},{v:'考研/深造率优先',l:'🎓 考研深造优先'}] },
        { id: 'q44_civil_service', type: 'radio', label: '是否计划考公务员/事业编', condition: cat => cat === '物理类',
          opts: [{v:'强烈意向',l:'强烈意向'},{v:'有考虑',l:'有考虑'},{v:'不考虑',l:'不考虑'}] },
        { id: 'q47_civil_service', type: 'radio', label: '是否计划考公务员/事业编', condition: cat => cat === '历史类',
          opts: [{v:'强烈意向',l:'强烈意向'},{v:'有考虑',l:'有考虑'},{v:'不考虑',l:'不考虑'}] },
      ]
    },{
      title: '专业与地域',
      questions: [
        { id: 'q45_target_industries', type: 'multi-select', label: '目标行业', condition: cat => cat === '物理类',
          opts: [{v:'信息技术/互联网',l:'💻 信息技术/互联网'},{v:'金融/银行',l:'🏦 金融/银行'},
                 {v:'教育/培训',l:'📚 教育/培训'},{v:'医疗/医药',l:'🏥 医疗/医药'},
                 {v:'工程/制造',l:'🏗️ 工程/制造'},{v:'法律/政务',l:'⚖️ 法律/政务'},
                 {v:'文化/传媒',l:'🎬 文化/传媒'},{v:'环境/能源',l:'🌱 环境/能源'}] },
        { id: 'q48_target_industries', type: 'multi-select', label: '目标行业', condition: cat => cat === '历史类',
          opts: [{v:'信息技术/互联网',l:'💻 信息技术/互联网'},{v:'金融/银行',l:'🏦 金融/银行'},
                 {v:'教育/培训',l:'📚 教育/培训'},{v:'医疗/医药',l:'🏥 医疗/医药'},
                 {v:'工程/制造',l:'🏗️ 工程/制造'},{v:'法律/政务',l:'⚖️ 法律/政务'},
                 {v:'文化/传媒',l:'🎬 文化/传媒'},{v:'环境/能源',l:'🌱 环境/能源'}] },
        { id: 'q46_medical_preference', type: 'radio', label: '是否想学医', condition: cat => cat === '物理类',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'不确定',l:'不确定'}] },
        { id: 'q49_medical_preference', type: 'radio', label: '是否想学医', condition: cat => cat === '历史类',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'不确定',l:'不确定'}] },
        { id: 'q48_teacher_preference', type: 'radio', label: '是否想当老师', condition: cat => cat === '物理类',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'不确定',l:'不确定'}] },
        { id: 'q50_teacher_preference', type: 'radio', label: '是否想当老师', condition: cat => cat === '历史类',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'不确定',l:'不确定'}] },
        { id: 'q56_province_preference', type: 'radio', label: '大学想在哪里读', required: true,
          opts: [{v:'优先省内，省外也可以',l:'📍 优先省内'},{v:'优先出省',l:'✈️ 优先出省'},
                 {v:'不限',l:'🌏 哪里都可以'}] },
        { id: 'q62_location_preference', type: 'radio', label: '更偏好哪个区域', hint: '如果都不在意的选"不限"',
          opts: [{v:'东部沿海',l:'🌊 东部沿海'},{v:'中部城市',l:'🏙️ 中部'},{v:'西部/西南',l:'🏔️ 西部/西南'},
                 {v:'北上广深',l:'🏙️ 一线城市'},{v:'不限',l:'不限'}] },
      ]
    }]
  },

  // ───── 第 7 步：志愿策略 ─────
  {
    icon: '⚙️', title: '志愿策略', desc: '了解你的风险偏好，调整冲稳保比例',
    groups: [{
      title: '策略偏好',
      questions: [
        { id: 'q60_stability_preference', type: 'radio', label: '对"铁饭碗"工作（公务员/国企）的渴望程度', required: true,
          opts: [{v:'非常渴望',l:'非常渴望（希望稳定压倒一切）'},{v:'比较渴望',l:'比较渴望'},{v:'无所谓',l:'无所谓'},
                 {v:'不太想',l:'不太想'},{v:'完全不想',l:'完全不想（追求挑战）'}] },
        { id: 'q56b_major_adjustment', type: 'radio', label: '是否服从专业调剂', condition: cat => cat === '物理类',
          hint: '不服从可能被退档，服从可能被调剂到不喜欢的专业',
          opts: [{v:'服从调剂',l:'✅ 服从（录取优先）'},{v:'不服从调剂',l:'⚠️ 不服从（专业优先）'}] },
        { id: 'q56b_major_adjustment_attitude', type: 'radio', label: '是否服从专业调剂', condition: cat => cat === '历史类',
          opts: [{v:'服从调剂',l:'✅ 服从（录取优先）'},{v:'不服从调剂',l:'⚠️ 不服从（专业优先）'}] },
        { id: 'q56c_strong_base', type: 'multi-select', label: '是否考虑特殊招生路径',
          opts: [{v:'强基计划',l:'🎯 强基计划'},{v:'综合评价',l:'📋 综合评价'},{v:'高水平运动队',l:'⚽ 高水平运动队'},
                 {v:'高水平艺术团',l:'🎭 高水平艺术团'},{v:'无',l:'无'}] },
        { id: 'q56d_collection_volunteer', type: 'radio', label: '是否愿意参加征集志愿',
          hint: '如果第一轮录取未投档成功，是否接受补录',
          opts: [{v:'愿意',l:'愿意'},{v:'不愿意',l:'不愿意'},{v:'视情况',l:'视情况而定'}] },
      ]
    }]
  },

  // ───── 第 8 步：职业与大学生活 ─────
  {
    icon: '💼', title: '职业与大学', desc: '聊聊你对未来大学生活和职业的设想',
    groups: [{
      title: '职业倾向',
      questions: [
        { id: 'q57_ideal_workday', type: 'multi-select', label: '你理想的工作状态是', condition: cat => cat === '物理类',
          opts: [{v:'自主安排',l:'⏰ 自主安排时间'},{v:'团队协作',l:'🤝 团队协作'},{v:'技术攻关',l:'🔬 技术/研究攻关'},
                 {v:'管理他人',l:'📊 带领/管理团队'},{v:'稳定清晰',l:'📋 按部就班稳定清晰'}] },
        { id: 'q58_ideal_workday', type: 'multi-select', label: '你理想的工作状态是', condition: cat => cat === '历史类',
          opts: [{v:'自主安排',l:'⏰ 自主安排时间'},{v:'团队协作',l:'🤝 团队协作'},{v:'技术攻关',l:'🔬 技术/研究攻关'},
                 {v:'管理他人',l:'📊 带领/管理团队'},{v:'稳定清晰',l:'📋 按部就班稳定清晰'}] },
        { id: 'q58_unacceptable_work', type: 'text', label: '最不能接受的工作类型', condition: cat => cat === '物理类', ph: '如 倒班制、应酬多、大量出差' },
        { id: 'q59_unacceptable_work', type: 'text', label: '最不能接受的工作类型', condition: cat => cat === '历史类', ph: '如 倒班制、应酬多、大量出差' },
        { id: 'q61_tech_iteration', type: 'radio', label: '如何看快速变化的技术行业', condition: cat => cat === '物理类',
          opts: [{v:'愿意持续学习',l:'🚀 愿意持续学习跟进'},{v:'有点压力',l:'😅 有点担心跟不上'},{v:'偏好稳定',l:'🛋️ 偏好稳定少变的行业'}] },
        { id: 'q62_tech_iteration', type: 'radio', label: '如何看快速变化的技术行业', condition: cat => cat === '历史类',
          opts: [{v:'愿意持续学习',l:'🚀 愿意持续学习跟进'},{v:'有点压力',l:'😅 有点担心跟不上'},{v:'偏好稳定',l:'🛋️ 偏好稳定少变的行业'}] },
      ]
    },{
      title: '大学生活',
      questions: [
        { id: 'q63_ideal_university', type: 'multi-select', label: '你心中的理想大学', condition: cat => cat === '物理类',
          opts: [{v:'学术氛围',l:'📖 浓厚学术氛围'},{v:'实践机会',l:'🔧 多实践机会'},{v:'国际交流',l:'🌍 国际交流机会多'},
                 {v:'社团活动',l:'🎉 丰富社团活动'},{v:'地理位置好',l:'📍 城市地理位置好'}] },
        { id: 'q64_ideal_university', type: 'multi-select', label: '你心中的理想大学', condition: cat => cat === '历史类',
          opts: [{v:'学术氛围',l:'📖 浓厚学术氛围'},{v:'实践机会',l:'🔧 多实践机会'},{v:'国际交流',l:'🌍 国际交流机会多'},
                 {v:'社团活动',l:'🎉 丰富社团活动'},{v:'地理位置好',l:'📍 城市地理位置好'}] },
        { id: 'q65_minor_attitude', type: 'radio', label: '是否计划辅修第二专业',
          opts: [{v:'是',l:'是'},{v:'否',l:'否'},{v:'看情况',l:'看情况'}] },
        { id: 'q66_further_study', type: 'multi-select', label: '深造意向', condition: cat => cat === '物理类',
          opts: [{v:'考研',l:'🎓 国内考研'},{v:'保研',l:'✨ 争取保研'},{v:'留学',l:'🌎 出国留学'},
                 {v:'不深造',l:'🚀 直接就业'},{v:'没想好',l:'🤔 没想好'}] },
        { id: 'q67_further_study', type: 'multi-select', label: '深造意向', condition: cat => cat === '历史类',
          opts: [{v:'考研',l:'🎓 国内考研'},{v:'保研',l:'✨ 争取保研'},{v:'留学',l:'🌎 出国留学'},
                 {v:'不深造',l:'🚀 直接就业'},{v:'没想好',l:'🤔 没想好'}] },
      ]
    }]
  },

  // ───── 第 9 步：项目自编学科自我评价 —— Likert 15 题 ─────
  {
    icon: '📐', title: '自我评估', desc: '请评估你在各学科的感受，每题 1-5 分',
    groups: [{
      title: '语文学科自我评价（项目自编）',
      questions: [
        { id: 'q76_se_cn1', type: 'likert', label: '我相信自己有很强的语文学习能力' },
        { id: 'q77_se_cn2', type: 'likert', label: '语文考试中我能很好地理解题目要求' },
        { id: 'q78_se_cn3', type: 'likert', label: '我擅长阅读和分析文本' },
        { id: 'q79_se_cn4', type: 'likert', label: '写作文时我能清晰地表达自己的想法' },
        { id: 'q80_se_cn5', type: 'likert', label: '我能记住并运用语文课上学到的知识' },
      ]
    },{
      title: '数学学科自我评价（项目自编）',
      questions: [
        { id: 'q81_se_mt1', type: 'likert', label: '数学对我来说容易理解和掌握' },
        { id: 'q82_se_mt2', type: 'likert', label: '面对数学难题我能坚持尝试不放弃' },
        { id: 'q83_se_mt3', type: 'likert', label: '我擅长把实际问题转化成数学问题' },
        { id: 'q84_se_mt4', type: 'likert', label: '数学课上我经常能先同学一步理解新概念' },
        { id: 'q85_se_mt5', type: 'likert', label: '我对解决数学题有信心' },
      ]
    },{
      title: '英语学科自我评价（项目自编）',
      questions: [
        { id: 'q86_se_en1', type: 'likert', label: '我觉得英语是一门容易掌握的语言' },
        { id: 'q87_se_en2', type: 'likert', label: '我能自信地用英语口头表达观点' },
        { id: 'q88_se_en3', type: 'likert', label: '我擅长英语阅读并理解复杂文章' },
        { id: 'q89_se_en4', type: 'likert', label: '英语听力部分我很少感到吃力' },
        { id: 'q90_se_en5', type: 'likert', label: '我有信心在英语考试中取得好成绩' },
      ]
    }]
  },

  // ───── 第 10 步：项目自编偏好问卷（职业价值 20 + 大五维度 50 + RIASEC 风格 76） ─────
  {
    icon: '🧬', title: '偏好探索', desc: '项目自编问卷，未经心理测量学验证、不作诊断；结果仅作专业方向参考',
    groups: [{
      title: '职业价值偏好问卷（项目自编）',
      sub: '每题 1-5 分，1=非常不符合 → 5=非常符合',
      questions: [
        { id: 'q91_cv_income1', type: 'likert', label: '我希望毕业后能拿到高薪' },
        { id: 'q92_cv_income2', type: 'likert', label: '经济回报是我选择工作的重要因素' },
        { id: 'q93_cv_stability1', type: 'likert', label: '稳定的工作对我来说很重要' },
        { id: 'q94_cv_stability2', type: 'likert', label: '我希望工作单位能提供长期保障' },
        { id: 'q95_cv_achievement1', type: 'likert', label: '成就感是我工作的主要动力' },
        { id: 'q96_cv_achievement2', type: 'likert', label: '我希望工作能让我有"做成大事"的感觉' },
        { id: 'q97_cv_help1', type: 'likert', label: '帮助他人让我感到快乐' },
        { id: 'q98_cv_help2', type: 'likert', label: '我希望我的工作能对社会有贡献' },
        { id: 'q99_cv_creative1', type: 'likert', label: '我喜欢工作需要发挥创造力' },
        { id: 'q100_cv_creative2', type: 'likert', label: '创造新东西是工作中最吸引我的部分' },
        { id: 'q101_cv_balance1', type: 'likert', label: '工作与生活的平衡比高薪更吸引我' },
        { id: 'q102_cv_balance2', type: 'likert', label: '我不想因为工作牺牲个人时间' },
        { id: 'q103_cv_leadership1', type: 'likert', label: '我喜欢在团队中担任领导角色' },
        { id: 'q104_cv_leadership2', type: 'likert', label: '我擅长组织和协调团队成员' },
        { id: 'q105_cv_autonomy1', type: 'likert', label: '我希望能自主决定工作方式' },
        { id: 'q106_cv_autonomy2', type: 'likert', label: '我不喜欢被过多干预和监管' },
        { id: 'q107_cv_location1', type: 'likert', label: '我想在家乡或熟悉的地方工作' },
        { id: 'q108_cv_location2', type: 'likert', label: '地理位置是我选工作的重要考量' },
        { id: 'q109_cv_learning1', type: 'likert', label: '工作中能学到新东西对我很重要' },
        { id: 'q110_cv_learning2', type: 'likert', label: '我喜欢需要持续学习的职业' },
      ]
    },{
      title: '大五维度偏好问卷（项目自编）',
      sub: '1=非常不符合 → 5=非常符合；未经心理测量验证，不作诊断',
      questions: [
        { id: 'bf01', type: 'likert', label: '我喜欢探索新想法和不同的看法' },
        { id: 'bf02', type: 'likert', label: '艺术、音乐或文学常常打动我' },
        { id: 'bf03', type: 'likert', label: '我愿意尝试不熟悉的食物或体验' },
        { id: 'bf04', type: 'likert', label: '我对哲学或抽象议题感兴趣' },
        { id: 'bf05', type: 'likert', label: '我喜欢动手尝试解决新问题' },
        { id: 'bf06', type: 'likert', label: '我喜欢思考"如果换一种做法会怎样"' },
        { id: 'bf07', type: 'likert', label: '我更喜欢按惯例做事，避免变动' },
        { id: 'bf08', type: 'likert', label: '抽象的话题对我来说没有吸引力' },
        { id: 'bf09', type: 'likert', label: '我会主动了解不同文化或行业的知识' },
        { id: 'bf10', type: 'likert', label: '我喜欢创造性的活动（写作/设计/艺术等）' },
        { id: 'bf11', type: 'likert', label: '我会把任务彻底完成，不留尾巴' },
        { id: 'bf12', type: 'likert', label: '我倾向于提前规划而不是临时应对' },
        { id: 'bf13', type: 'likert', label: '我重视秩序，物品归位让我安心' },
        { id: 'bf14', type: 'likert', label: '我守时，承诺的事会按期完成' },
        { id: 'bf15', type: 'likert', label: '面对长远目标我能保持耐心和坚持' },
        { id: 'bf16', type: 'likert', label: '我容易拖延或半途而废' },
        { id: 'bf17', type: 'likert', label: '我做决定前喜欢权衡利弊' },
        { id: 'bf18', type: 'likert', label: '我有时会忽略细节、马虎处理' },
        { id: 'bf19', type: 'likert', label: '我能严格自律，控制冲动' },
        { id: 'bf20', type: 'likert', label: '我倾向于按计划行事，按部就班' },
        { id: 'bf21', type: 'likert', label: '我喜欢和很多人一起参加活动' },
        { id: 'bf22', type: 'likert', label: '在群体中我容易主动开口、活跃气氛' },
        { id: 'bf23', type: 'likert', label: '我精力充沛，喜欢忙碌的节奏' },
        { id: 'bf24', type: 'likert', label: '我容易结识新朋友' },
        { id: 'bf25', type: 'likert', label: '我喜欢成为团队中受关注的人' },
        { id: 'bf26', type: 'likert', label: '社交活动会让我感到充电而不是疲惫' },
        { id: 'bf27', type: 'likert', label: '我更喜欢独处或小范围交流' },
        { id: 'bf28', type: 'likert', label: '在陌生场合我会显得比较安静' },
        { id: 'bf29', type: 'likert', label: '我习惯先表达想法，再细致斟酌' },
        { id: 'bf30', type: 'likert', label: '我喜欢热闹、节奏快的环境' },
        { id: 'bf31', type: 'likert', label: '我习惯先体谅别人的处境' },
        { id: 'bf32', type: 'likert', label: '我相信大多数人本质上是善意的' },
        { id: 'bf33', type: 'likert', label: '我愿意帮别人，即使没有回报' },
        { id: 'bf34', type: 'likert', label: '面对冲突我倾向于先寻求和解' },
        { id: 'bf35', type: 'likert', label: '我会主动让步以维护团队和谐' },
        { id: 'bf36', type: 'likert', label: '我对他人的情绪比较敏感' },
        { id: 'bf37', type: 'likert', label: '我对别人会保持戒备和怀疑' },
        { id: 'bf38', type: 'likert', label: '我倾向于直接指出对方的问题' },
        { id: 'bf39', type: 'likert', label: '我能耐心倾听别人的倾诉' },
        { id: 'bf40', type: 'likert', label: '我重视集体利益高于个人喜好' },
        { id: 'bf41', type: 'likert', label: '我容易感到紧张或焦虑' },
        { id: 'bf42', type: 'likert', label: '我的情绪起伏比较明显' },
        { id: 'bf43', type: 'likert', label: '小事也会让我心烦很久' },
        { id: 'bf44', type: 'likert', label: '我经常担心事情会出错' },
        { id: 'bf45', type: 'likert', label: '压力大时我容易感到无力' },
        { id: 'bf46', type: 'likert', label: '别人的批评会让我难过较长时间' },
        { id: 'bf47', type: 'likert', label: '即使遇到困难我也能保持冷静' },
        { id: 'bf48', type: 'likert', label: '我能很快从负面情绪中恢复' },
        { id: 'bf49', type: 'likert', label: '我有时会无来由地情绪低落' },
        { id: 'bf50', type: 'likert', label: '面对未知我容易感到不安' },
      ]
    }]
  },
];
