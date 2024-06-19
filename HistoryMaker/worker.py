"""Pipeline."""
from loguru import logger
from .llm_client import ChatClient

class HISTORY_WORKER:
    def __init__(self, config_path: str, language: str = 'zh'):
        '''
        ## medbench病史要求
        https://medbench.opencompass.org.cn/dataset
        诊疗报告，包含六部分：
        (1) 主诉： 主要症状或体征 
        (2) 现病史： 主要症状的描述（发病情况，发病时间） 
        (3) 辅助检查：病人已有的检查项目、检查结果、会诊记录等 
        (4) 既往史：既往的健康状况、过去曾经患过的疾病等 
        (5) 诊断：对疾病的诊断 
        (6) 建议：检查建议、药物治疗、注意事项。
        
        ## 卫健委病史要求
        http://www.nhc.gov.cn/wjw/gfxwj/201304/1917f257cd774afa835cff168dc4ea41.shtml
        （一）患者一般情况包括姓名、性别、年龄、民族、婚姻状况、出生地、职业、入院时间、记录时间、病史陈述者。
        （二）主诉是指促使患者就诊的主要症状（或体征）及持续时间。
        （三）现病史是指患者本次疾病的发生、演变、诊疗等方面的详细情况，应当按时间顺序书写。内容包括发病情况、主要症状特点及其发展变化情况、伴随症状、发病后诊疗经过及结果、睡眠和饮食等一般情况的变化，以及与鉴别诊断有关的阳性或阴性资料等。

        1.发病情况：记录发病的时间、地点、起病缓急、前驱症状、可能的原因或诱因。
        2.主要症状特点及其发展变化情况：按发生的先后顺序描述主要症状的部位、性质、持续时间、程度、缓解或加剧因素，以及演变发展情况。
        3.伴随症状：记录伴随症状，描述伴随症状与主要症状之间的相互关系。
        4.发病以来诊治经过及结果：记录患者发病后到入院前，在院内、外接受检查与治疗的详细经过及效果。对患者提供的药名、诊断和手术名称需加引号（“”）以示区别。
        5.发病以来一般情况：简要记录患者发病后的精神状态、睡眠、食欲、大小便、体重等情况。

        与本次疾病虽无紧密关系、但仍需治疗的其他疾病情况，可在现病史后另起一段予以记录。
        '''
        self.language = language
        self.llm = ChatClient(config_path=config_path) #每次实例化worker都会重新实例化chatclient并读取本地最新的配置文件
        if self.language == 'zh':
            self.requirement ={
                "MAIN_SYMPTOM": "促使患者就诊的主要症状（或体征）及持续时间",
                "PRESENT_HISTORY_ONSET": "发病的时间、地点、起病缓急、前驱症状、可能的原因或诱因",
                "PRESENT_HISTORY_DESCRIPTION": "主要症状的部位、性质、持续时间、程度、缓解或加剧因素，以及演变发展情况",
                "PRESENT_HISTORY_ACCOMPANY": "伴随症状，描述伴随症状与主要症状之间的相互关系",
                "PRESENT_HISTORY_TREATMENT": "患者发病后到入院前，在院内、外接受检查与治疗的详细经过及效果",
                "PRESENT_HISTORY_GENERAL": "患者发病后的精神状态、睡眠、食欲、大小便、体重等情况",
                "EXAMINATION": "患者已有的检查项目、检查结果",
                "PAST_HISTORY": "既往的健康状况、过去曾经患过的疾病",
                "DIAGNOSIS": "对疾病的诊断",
                "SUGGESTION": "检查建议、药物治疗、注意事项"
            }
        else:
            self.requirement ={
                "MAIN_SYMPTOM": "The main symptoms (or signs) that prompted the patient to seek medical attention and their duration",
                "PRESENT_HISTORY_ONSET": "The time and place of onset, the acuteness of onset, prodromal symptoms, and possible causes or precipitating factors",
                "PRESENT_HISTORY_DESCRIPTION": "The location, nature, duration, severity, relieving or aggravating factors of the main symptoms, as well as their evolution in chronological order",
                "PRESENT_HISTORY_ACCOMPANY": "Accompanying symptoms, describe the relationship between accompanying symptoms and main symptoms",
                "PRESENT_HISTORY_TREATMENT": "The detailed process and results of examinations and treatments received by the patient inside or outside the hospital before admission",
                "PRESENT_HISTORY_GENERAL": "The patient's mental state, sleep, appetite, bowel movements, weight, etc., after the onset",
                "EXAMINATION": "Existing test items and results",
                "PAST_HISTORY": "Past health status, previous diseases",
                "DIAGNOSIS": "Diagnosis of the disease",
                "SUGGESTION": "Examination suggestions, medication treatments, precautions"
            }

        if self.language == 'zh':
            self.BASIC_INFO_TEMPLATE = '请提取患者的基本信息：包含姓名、性别、年龄、职业、婚姻状况、住址。避免口语化表达，避免包含其他内容。示例：对话：……；基本信息：患者姓名张三，男，45岁，农民，不详，住址不详。对话：{}；基本信息：'
            self.MAIN_SYMPTOM_TEMPLATE = '请提取患者的主诉：包含主要症状（或体征）及持续时间。避免口语化表达，避免包含其他内容。示例：对话：宝宝咳嗽，昨天开始，今天咳嗽比昨天多，有痰声，流鼻涕；主诉：咳嗽两天。对话：{}；主诉：'
            self.PRESENT_HISTORY_ONSET_TEMPLATE = '请提取患者的现病史中的起病情况：记录发病的时间、地点、起病缓急、前驱症状、可能的原因或诱因。避免口语化表达，避免包含其他内容。示例：对话：……；现病史起病：患者于3天前发热，起病急，无明显前驱症状，无明显诱因。对话：{}；现病史起病：'
            self.PRESENT_HISTORY_DESCRIPTION_TEMPLATE = '请提取患者的现病史中主要症状特点及其发展变化情况：按发生的先后顺序描述主要症状的部位、性质、持续时间、程度、缓解或加剧因素，以及演变发展情况。？避免口语化表达，避免包含其他内容。示例：对话：……；现病史描述：患者发热3天，体温最高38.5℃，伴咳嗽，咳痰，咳痰量约30ml/次，痰白色，无明显加重因素，无明显缓解因素。示例：对话：……；现病史描述：患者无其他伴随症状。对话：{}；现病史描述：'
            self.PRESENT_HISTORY_ACCOMPANY_TEMPLATE = '请提取患者的现病史中伴随症状：记录伴随症状，描述伴随症状与主要症状之间的相互关系。避免口语化表达，避免包含其他内容。示例：对话：……；现病史伴随：伴咳嗽，咳痰，无胸痛，无咯血，无气促。对话：{}；现病史伴随：'
            self.PRESENT_HISTORY_TREATMENT_TEMPLATE = '请提取患者此次就诊之前的诊治经过及结果，如无填写无。避免口语化表达，避免包含其他内容。示例：对话：……；现病史诊治：患者发病后就诊于当地医院，予以抗生素治疗，效果不佳，遂来我院就诊。对话：……；现病史诊治：患者此前未就诊。对话：{}；现病史诊治：'
            self.PRESENT_HISTORY_GENERAL_TEMPLATE = '请提取患者的现病史中发病以来一般情况：简要记录患者发病后的精神状态、睡眠、食欲、大小便、体重等情况。避免口语化表达，避免包含其他内容。示例：对话：……；现病史一般情况：患者自发病以来精神状态一般，食欲减退，睡眠不好，大小便正常，体重无明显变化。示例：对话：……；现病史一般情况：患者一般情况无殊。对话：{}；现病史一般情况：'
            self.EXAMINATION_TEMPLATE = '请提取患者的辅助检查：病人已有的检查项目、检查结果。避免口语化表达，避免包含其他内容。示例：对话：……；辅助检查：患者自发病以来查血常规：白细胞计数10.0×10^9/L。胸片：双肺纹理增多，未见实变。对话：……；辅助检查：无。对话：{}；辅助检查：'
            self.PAST_HISTORY_TEMPLATE = '请提取患者的既往史：既往的健康状况、过去曾经患过的疾病等。避免口语化表达，避免包含其他内容。示例：对话：……；既往史：患者既往体健，无慢性病史，手术史不详，输血史不详。对话：{}；既往史：'
            self.DIAGNOSIS_TEMPLATE = '请提取患者的诊断：对疾病的诊断。避免口语化表达，避免包含其他内容。示例：对话：……；诊断：急性支气管炎。对话：{}；诊断：'
            self.SUGGESTION_TEMPLATE = '请提取患者的建议：检查建议、药物治疗、注意事项。避免口语化表达，避免包含其他内容。示例：对话：……；建议：1.继续抗生素治疗，2.注意休息，3.多饮水。对话：{}；建议：'
            self.RPOFESSIONAL_EXPRESSION_TEMPLATE = '请把该段医学描述转化为专业表达，并按照要求删除多余的内容。示例：原句：3天拉不出粑粑，之前在小儿科就诊未见好转，要求：促使患者就诊的主要症状（或体征）及持续时间，专业表达：便秘3天。原句：{}，要求：{}，专业表达：'
        else:
            self.BASIC_INFO_TEMPLATE = "Please provide the patient's basic information: includes name, gender, age, occupation, marital status, and address. Example: Dialogue: ......, Basic Information: Patient's name Zhang San, male, 45 years old, farmer, marital status and address unknown. Dialogue: {}, Basic Information: "
            self.MAIN_SYMPTOM_TEMPLATE = "Please tell me the patient's chief complaint: includes the main symptom(s) or signs and their duration. Example: Dialogue: ......, Chief Complaint: Fever for 3 days. Dialogue: {}, Chief Complaint: "
            self.PRESENT_HISTORY_ONSET_TEMPLATE = "Please tell me the onset conditions in the patient's present illness history: record the time and place of onset, the acuteness of onset, prodromal symptoms, and possible causes or precipitating factors. Example: Dialogue: ......, Present Illness Onset: The patient had a fever 3 days ago, with sudden onset, no obvious prodromal symptoms, and no apparent cause. Dialogue: {}, Present Illness Onset: The patient started "
            self.PRESENT_HISTORY_DESCRIPTION_TEMPLATE = "Please tell me about the main symptom characteristics and their development in the patient's present illness history: describe the location, nature, duration, severity, relieving or aggravating factors of the main symptoms, as well as their evolution in chronological order. Example: Dialogue: ......, Present Illness Description: The patient has had a fever for 3 days, with a maximum temperature of 38.5°C, accompanied by coughing, phlegm production approximately 30ml per occurrence, white phlegm, no significant aggravating or relieving factors. Dialogue: {}, Present Illness Description: "
            self.PRESENT_HISTORY_ACCOMPANY_TEMPLATE = "Please tell me the accompanying symptoms in the patient's present illness history: record accompanying symptoms and describe their relationship with the main symptoms. Example: Dialogue: ......, Present Illness Accompanying: Accompanied by cough, phlegm production, no chest pain, no hemoptysis, no dyspnea. Dialogue: {}, Present Illness Accompanying: Accompanied by "
            self.PRESENT_HISTORY_TREATMENT_TEMPLATE = "Please tell me about the diagnosis and treatment history since the onset of the patient's illness: record the detailed process and results of examinations and treatments received by the patient inside or outside the hospital before admission. Names of medications, diagnoses, and surgical procedures should be quoted to distinguish them. Example: Dialogue: ......, Present Illness Treatment: After the onset, the patient was treated with antibiotics at a local hospital with poor results, and then came to our hospital. Dialogue: {}, Present Illness Treatment: "
            self.PRESENT_HISTORY_GENERAL_TEMPLATE = "Please tell me about the general condition of the patient since the onset of the illness: briefly record the patient's mental state, sleep, appetite, bowel movements, weight, etc., after the onset. Example: Dialogue: ......, Present Illness General: Since the onset, the patient has been in a general mental state, with reduced appetite, poor sleep, normal bowel movements, and no significant weight changes. Dialogue: {}, Present Illness General: Since the onset "
            self.EXAMINATION_TEMPLATE = "Please tell me about the patient's auxiliary examinations: existing test items and results. Example: Dialogue: ......, Examination: Since the onset, the patient has undergone a complete blood count: white blood cell count 10.0×10^9/L, neutrophil count 7.0×10^9/L, lymphocyte count 2.0×10^9/L, hemoglobin 120g/L, platelet count 200×10^9/L. Chest X-ray: Increased lung markings, no consolidation observed. Dialogue: {}, Examination: Since the onset, the patient has been tested for "
            self.PAST_HISTORY_TEMPLATE = "Please tell me about the patient's past medical history: past health status, previous diseases, etc. Example: Dialogue: ......, Past History: The patient was previously healthy, no history of chronic diseases, surgical history and transfusion history are unknown. Dialogue: {}, Past History: Previously "
            self.DIAGNOSIS_TEMPLATE = "Please tell me the patient's diagnosis: diagnosis of the disease. Example: Dialogue: ......, Diagnosis: Acute bronchitis. Dialogue: {}, Diagnosis: "
            self.SUGGESTION_TEMPLATE = "Please tell me the patient's recommendations: examination suggestions, medication treatments, precautions. Example: Dialogue: ......, Suggestion: 1. Continue antibiotic treatment, 2. Ensure rest, 3. Drink plenty of water. Dialogue: {}, Suggestion: "


    def generate_history(self,dialog):
        '''
        生成病历
        '''
        history_extracted = {}
        # history_extracted['BASIC_INFO'] = self.llm.generate_response(prompt=self.BASIC_INFO_TEMPLATE.format(dialog),
        #                                             backend=backend,
        #                                             history=[])
        # logger.info('BASIC_INFO:{}'.format(history_extracted['BASIC_INFO']))
        history_extracted['MAIN_SYMPTOM'] = self.llm.generate_response(prompt=self.MAIN_SYMPTOM_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('MAIN_SYMPTOM:{}'.format(history_extracted['MAIN_SYMPTOM']))

        history_extracted['PRESENT_HISTORY_ONSET'] = self.llm.generate_response(prompt=self.PRESENT_HISTORY_ONSET_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('PRESENT_HISTORY_ONSET:{}'.format(history_extracted['PRESENT_HISTORY_ONSET']))

        history_extracted['PRESENT_HISTORY_DESCRIPTION'] = self.llm.generate_response(prompt=self.PRESENT_HISTORY_DESCRIPTION_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('PRESENT_HISTORY_DESCRIPTION:{}'.format(history_extracted['PRESENT_HISTORY_DESCRIPTION']))

        history_extracted['PRESENT_HISTORY_ACCOMPANY'] = self.llm.generate_response(prompt=self.PRESENT_HISTORY_ACCOMPANY_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('PRESENT_HISTORY_ACCOMPANY:{}'.format(history_extracted['PRESENT_HISTORY_ACCOMPANY']))

        history_extracted['PRESENT_HISTORY_TREATMENT'] = self.llm.generate_response(prompt=self.PRESENT_HISTORY_TREATMENT_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('PRESENT_HISTORY_TREATMENT:{}'.format(history_extracted['PRESENT_HISTORY_TREATMENT']))

        history_extracted['PRESENT_HISTORY_GENERAL'] = self.llm.generate_response(prompt=self.PRESENT_HISTORY_GENERAL_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('PRESENT_HISTORY_GENERAL:{}'.format(history_extracted['PRESENT_HISTORY_GENERAL']))

        history_extracted['EXAMINATION'] = self.llm.generate_response(prompt=self.EXAMINATION_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('EXAMINATION:{}'.format(history_extracted['EXAMINATION']))

        history_extracted['PAST_HISTORY'] = self.llm.generate_response(prompt=self.PAST_HISTORY_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('PAST_HISTORY:{}'.format(history_extracted['PAST_HISTORY']))
        history_extracted['DIAGNOSIS'] = self.llm.generate_response(prompt=self.DIAGNOSIS_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('DIAGNOSIS:{}'.format(history_extracted['DIAGNOSIS']))

        history_extracted['SUGGESTION'] = self.llm.generate_response(prompt=self.SUGGESTION_TEMPLATE.format(dialog),
                                                    backend='remote1',
                                                    history=[])
        logger.info('SUGGESTION:{}'.format(history_extracted['SUGGESTION']))

        return history_extracted

    def modify_history(self,history):
        newhistory = {}
        for key in ['MAIN_SYMPTOM','EXAMINATION','PAST_HISTORY','DIAGNOSIS','SUGGESTION']:
            originial_text = history[key]
            modified_text = self.llm.generate_response(prompt= self.RPOFESSIONAL_EXPRESSION_TEMPLATE.format(originial_text,self.requirement[key]),
                                                    backend='remote1',
                                                    history=[])
            newhistory[key] = modified_text

        phkeys = ['PRESENT_HISTORY_ONSET','PRESENT_HISTORY_DESCRIPTION','PRESENT_HISTORY_ACCOMPANY','PRESENT_HISTORY_TREATMENT','PRESENT_HISTORY_GENERAL']
        ph = ' '.join([history[key] for key in phkeys])
        phreq = ' '.join([self.requirement[key] for key in phkeys])
        newph = self.llm.generate_response(prompt= self.RPOFESSIONAL_EXPRESSION_TEMPLATE.format(ph, phreq),
                                                    backend='remote1',
                                                    history=[])
        newhistory['PRESENT_HISTORY'] = newph
        return newhistory
    
    def generate_text(self,history):
        '''
        生成文本
        '''
        text = ''
        
        text += "主诉：" + history['MAIN_SYMPTOM'] + '\n'
        text += "现病史：" + history['PRESENT_HISTORY'] + '\n'
        text += "辅助检查：" + history['EXAMINATION'] + '\n'
        text += "既往史：" + history['PAST_HISTORY'] + '\n'
        text += "诊断：" + history['DIAGNOSIS'] + '\n'
        text += "建议：" + history['SUGGESTION']
        return text