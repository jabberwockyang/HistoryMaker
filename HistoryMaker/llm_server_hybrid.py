# Copyright (c) OpenMMLab. All rights reserved.
"""LLM server proxy."""
import argparse
import json
import os
import random
import time
from datetime import datetime, timedelta
from multiprocessing import Process, Value
import asyncio # yyj
import pytoml
import requests
from aiohttp import web
from aiohttp.web_runner import AppRunner
from loguru import logger
from openai import OpenAI
from transformers import AutoModelForCausalLM, AutoTokenizer

os.environ["TOKENIZERS_PARALLELISM"] = "false"
def check_gpu_max_memory_gb():
    try:
        import torch
        device = torch.device('cuda')
        return torch.cuda.get_device_properties(
            device).total_memory / (  # noqa E501
                1 << 30)
    except Exception as e:
        logger.error(str(e))
    return -1


def build_messages(prompt, history, system: str = None):
    messages = []
    if system is not None and len(system) > 0:
        messages.append({'role': 'system', 'content': system})
    for item in history:
        messages.append({'role': 'user', 'content': item[0]})
        messages.append({'role': 'assistant', 'content': item[1]})
    messages.append({'role': 'user', 'content': prompt})
    return messages


def os_run(cmd: str):
    ret = os.popen(cmd)
    ret = ret.read().rstrip().lstrip()
    return ret


class RPM:

    def __init__(self, rpm: int = 30):
        self.rpm = rpm
        self.record = {'slot': self.get_minute_slot(), 'counter': 0}

    def get_minute_slot(self):
        current_time = time.time()
        dt_object = datetime.fromtimestamp(current_time)
        total_minutes_since_midnight = dt_object.hour * 60 + dt_object.minute
        return total_minutes_since_midnight

    def wait(self):
        current = time.time()
        dt_object = datetime.fromtimestamp(current)
        minute_slot = self.get_minute_slot()

        if self.record['slot'] == minute_slot:
            # check RPM exceed
            if self.record['counter'] >= self.rpm:
                # wait until next minute
                next_minute = dt_object.replace(
                    second=0, microsecond=0) + timedelta(minutes=1)
                _next = next_minute.timestamp()
                sleep_time = abs(_next - current)
                time.sleep(sleep_time)

                self.record = {'slot': self.get_minute_slot(), 'counter': 0}
        else:
            self.record = {'slot': self.get_minute_slot(), 'counter': 0}
        self.record['counter'] += 1
        logger.debug(self.record)


class InferenceWrapper:
    """A class to wrapper kinds of inference framework."""

    def __init__(self, model_path: str):
        """Init model handler."""

        if check_gpu_max_memory_gb() < 20:
            logger.warning(
                'GPU mem < 20GB, try Experience Version or set llm.server.local_llm_path="Qwen/Qwen-7B-Chat-Int8" in `config.ini`'  # noqa E501
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_path,
                                                       trust_remote_code=True)

        if 'qwen1.5' in model_path.lower():
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path, device_map='auto', trust_remote_code=True).eval()
        elif 'qwen' in model_path.lower():
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                device_map='auto',
                trust_remote_code=True,
                use_cache_quantization=True,
                use_cache_kernel=True,
                use_flash_attn=False).eval()
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                trust_remote_code=True,
                device_map='auto',
                torch_dtype='auto').eval()

    def chat(self, prompt: str, history=[]):
        """Generate a response from local LLM.

        Args:
            prompt (str): The prompt for inference.
            history (list): List of previous interactions.

        Returns:
            str: Generated response.
        """
        output_text = ''

        if type(self.model).__name__ == 'Qwen2ForCausalLM':
            messages = build_messages(
                prompt=prompt,
                history=history,
                system='You are a helpful assistant')  # noqa E501
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
            model_inputs = self.tokenizer([text],
                                          return_tensors='pt').to('cuda')
            generated_ids = self.model.generate(model_inputs.input_ids,
                                                max_new_tokens=512,
                                                top_k=1)
            generated_ids = [
                output_ids[len(input_ids):] for input_ids, output_ids in zip(
                    model_inputs.input_ids, generated_ids)
            ]

            output_text = self.tokenizer.batch_decode(
                generated_ids, skip_special_tokens=True)[0]
        else:
            output_text, _ = self.model.chat(self.tokenizer,
                                             prompt,
                                             history,
                                             top_k=1,
                                             do_sample=False)
        return output_text


class HybridLLMServer:
    """A class to handle server-side interactions with a hybrid language
    learning model (LLM) service.

    This class is responsible for initializing the local and remote LLMs,
    generating responses from these models as per the provided configuration,
    and handling retries in case of failures.
    """

    def __init__(self,
                 llm_config: dict,
                 device: str = 'cuda',
                 retry=2,
                 config_path = 'config.ini') -> None:
        """Initialize the HybridLLMServer with the given configuration, device,
        and number of retries."""
        self.device = device
        self.retry = retry
        self.llm_config = llm_config
        self.config_path = config_path
        self.server_config = llm_config['server']
        self.enable_remote = llm_config['enable_remote'] 
        self.enable_local = llm_config['enable_local']

        self.local_max_length = self.server_config['local_llm_max_text_length']
        # self.remote_max_length = self.server_config[
        #     'remote_llm_max_text_length']
        # self.remote_type = self.server_config['remote_type']

        model_path = self.server_config['local_llm_path']

        _rpm = 500
        if 'rpm' in self.server_config:
            _rpm = self.server_config['rpm']
        self.rpm = RPM(_rpm)
        self.token = ('', 0)
        if self.enable_local:
            self.inference = InferenceWrapper(model_path)
        else:
            logger.warning('local LLM disabled.')

    def reload_config(self,backend):
        with open (self.config_path,'r', encoding='utf8') as f:
            self.llm_config = pytoml.load(f)['llm']
        # self.server_config = self.llm_config['server']

        if backend == 'remote1':
            self.remote_config = self.llm_config['remote1']
        elif backend == 'remote2':
            self.remote_config = self.llm_config['remote2']
        else:
            logger.error('unknow backend {}'.format(backend))
            return
        
        self.remote_type = self.remote_config['remote_type']
        self.remote_model = self.remote_config['remote_llm_model']
        self.remote_max_length = self.remote_config['remote_llm_max_text_length']
        self.api_key = self.remote_config['remote_api_key']
        self.base_url = self.remote_config['remote_base_url']



    def call_puyu(self, prompt, history):
        
        url = 'https://puyu.openxlab.org.cn/puyu/api/v1/chat/completion'

        now = time.time()
        if int(now - self.token[1]) >= 1800:
            logger.debug('refresh token {}'.format(time.time()))
            self.token = (os_run('openxlab token'), time.time())

        header = {
            'Content-Type': 'application/json',
            'Authorization': self.token[0]
        }

        logger.info('prompt length {}'.format(len(prompt)))
        history = history[-4:]

        messages = []
        for item in history:
            messages.append({'role': 'user', 'content': item[0]})
            messages.append({'role': 'assistant', 'content': item[1]})
        messages.append({'role': 'user', 'content': prompt})

        data = {
            'model': 'internlm2-20b-latest',
            'messages': messages,
            'n': 1,
            'disable_report': False,
            'top_p': 0.9,
            'temperature': 0.8,
            'request_output_len': 2048
        }

        output_text = ''
        self.rpm.wait()

        life = 0
        while life < self.retry:
            try:
                res_json = requests.post(url,
                                         headers=header,
                                         data=json.dumps(data),
                                         timeout=120).json()
                logger.debug(res_json)

                # fix token
                if 'msgCode' in res_json and res_json['msgCode'] == 'A0202':
                    # token error retry
                    logger.error('token error, try refresh')
                    self.token = (os_run('openxlab token'), time.time())
                    header = {
                        'Content-Type': 'application/json',
                        'Authorization': self.token[0]
                    }
                    res_json = requests.post(url,
                                             headers=header,
                                             data=json.dumps(data),
                                             timeout=120).json()
                    logger.debug(res_json)

                res_data = res_json['data']
                if len(res_data) < 1:
                    logger.error('debug:')
                    logger.error(res_json)
                    return output_text
                output_text = res_data['choices'][0]['text']

                logger.info(res_json)
                if '仩嗨亾笁潪能實験厔' in output_text:
                    raise Exception('internlm model waterprint !!!')
                return output_text

            except Exception as e:
                with open('badcase{}.txt'.format(life), 'w') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.error(str(e))
                self.token = (os_run('openxlab token'), time.time())
                header = {
                    'Content-Type': 'application/json',
                    'Authorization': self.token[0]
                }

                life += 1
        return output_text

    def call_kimi(self, prompt, history):
        """Generate a response from Kimi (a remote LLM).

        Args:
            prompt (str): The prompt to send to Kimi.
            history (list): List of previous interactions.

        Returns:
            str: Generated response from Kimi.
        """
        
        client = OpenAI(
            api_key=self.api_key,
            base_url='https://api.moonshot.cn/v1',
        )

        SYSTEM = '你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一些涉及恐怖主义，种族歧视，黄色暴力，政治宗教等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。'  # noqa E501
        messages = build_messages(prompt=prompt,
                                  history=history,
                                  system=SYSTEM)

        life = 0
        while life < self.retry:
            try:
                logger.debug('remote api sending: {}'.format(messages))
                completion = client.chat.completions.create(
                    model=self.server_config['remote_llm_model'],
                    messages=messages,
                    temperature=0.0,
                )
                return completion.choices[0].message.content
            except Exception as e:
                logger.error(str(e))
                # retry
                life += 1
                randval = random.randint(1, int(pow(2, life)))
                time.sleep(randval)
        return ''

    def call_gpt(self,
                 prompt,
                 history,
                 base_url: str = None,
                 system: str = None):
        """Generate a response from openai API.

        Args:
            prompt (str): The prompt to send to openai API.
            history (list): List of previous interactions.

        Returns:
            str: Generated response from RPC.
        """
        
        if base_url is not None:
            client = OpenAI(api_key=self.api_key,
                            base_url=base_url)
        elif self.base_url != '':
            client = OpenAI(api_key=self.api_key,
                            base_url=self.base_url)
        else:
            client = OpenAI(api_key=self.api_key)

        messages = build_messages(prompt=prompt,
                                  history=history,
                                  system=system)

        life = 0
        while life < self.retry:
            try:
                logger.debug('remote api sending: {}'.format(messages))
                completion = client.chat.completions.create(
                    model=self.remote_model,
                    messages=messages,
                    temperature=0.0,
                )
                return completion.choices[0].message.content
            except Exception as e:
                logger.error(str(e))
                # retry
                life += 1
                randval = random.randint(1, int(pow(3, life)))
                time.sleep(randval)
        return ''

    def call_deepseek(self, prompt, history):
        """Generate a response from deepseek (a remote LLM).

        Args:
            prompt (str): The prompt to send.
            history (list): List of previous interactions.

        Returns:
            str: Generated response.
        """
        
        client = OpenAI(
            api_key=self.api_key,
            base_url='https://api.deepseek.com/v1',
        )

        messages = build_messages(
            prompt=prompt,
            history=history,
            system='You are a helpful assistant')  # noqa E501

        life = 0
        while life < self.retry:
            try:
                logger.debug('remote api sending: {}'.format(messages))
                completion = client.chat.completions.create(
                    model=self.server_config['remote_llm_model'],
                    messages=messages,
                    temperature=0.1,
                )
                return completion.choices[0].message.content
            except Exception as e:
                logger.error(str(e))
                # retry
                life += 1
                randval = random.randint(1, int(pow(2, life)))
                time.sleep(randval)
        return ''

    def call_zhipuai(self, prompt, history):
        """Generate a response from zhipuai (a remote LLM).

        Args:
            prompt (str): The prompt to send.
            history (list): List of previous interactions.

        Returns:
            str: Generated response.
        """
        
        try:
            from zhipuai import ZhipuAI
            client = ZhipuAI(api_key=self.api_key)
        except Exception as e:
            logger.error(str(e))
            logger.error('please `pip install zhipuai` and check API_KEY')
            return ''

        messages = build_messages(
            prompt=prompt,
            history=history,
            system='You are a helpful assistant')  # noqa E501

        life = 0
        while life < self.retry:
            try:
                logger.debug('remote api sending: {}'.format(messages))
                completion = client.chat.completions.create(
                    model=self.server_config['remote_llm_model'],
                    messages=messages,
                    temperature=0.1,
                )
                return completion.choices[0].message.content
            except Exception as e:
                logger.error(str(e))
                # retry
                life += 1
                randval = random.randint(1, int(pow(2, life)))
                time.sleep(randval)
        return ''

    def call_alles_apin(self, prompt: str, history: list):
        
        self.rpm.wait()

        url = 'https://openxlab.org.cn/gw/alles-apin-hub/v1/openai/v2/text/chat'
        headers = {
            'content-type': 'application/json',
            'alles-apin-token': self.api_key
        }

        messages = build_messages(prompt=prompt, history=history)

        payload = {'model': 'gpt-4-1106-preview', 'messages': messages}

        response = requests.post(url,
                                 headers=headers,
                                 data=json.dumps(payload))

        text = ''
        resp_json = response.json()
        if resp_json['msgCode'] == '10000':
            data = resp_json['data']
            if len(data['choices']) > 0:
                text = data['choices'][0]['message']['content']
        return text

    def generate_response(self, prompt, history=[], backend='local'): 
        """Generate a response from the appropriate LLM based on the
        configuration.

        Args:
            prompt (str): The prompt to send to the LLM.
            history (list, optional): List of previous interactions. Defaults to [].  # noqa E501
            remote (bool, optional): Flag to determine whether to use a remote server. Defaults to False.  # noqa E501

        Returns:
            str: Generated response from the LLM.
        """
        output_text = ''
        time_tokenizer = time.time()
        self.reload_config(backend=backend)

        if backend == 'local':
            prompt = prompt[0:self.local_max_length]
            """# Caution: For the results of this software to be reliable and verifiable,  # noqa E501
            it's essential to ensure reproducibility. Thus `GenerationMode.GREEDY_SEARCH`  # noqa E501
            must enabled."""

            output_text = self.inference.chat(prompt, history)

        else:
            remote_type = self.remote_type
            prompt = prompt[0:self.remote_max_length]

            if remote_type == 'kimi':
                output_text = self.call_kimi(prompt=prompt, history=history)
            elif remote_type == 'deepseek':
                output_text = self.call_deepseek(prompt=prompt,
                                                 history=history)
            elif remote_type == 'zhipuai':
                output_text = self.call_zhipuai(prompt=prompt, history=history)

            elif remote_type == 'xi-api' or remote_type == 'gpt':
                base_url = None
                system = None
                if remote_type == 'xi-api':
                    base_url = 'https://api.xi-ai.cn/v1'
                    system = 'You are a helpful assistant.'
                output_text = self.call_gpt(prompt=prompt,
                                            history=history,
                                            system=system)

            elif remote_type == 'puyu':
                output_text = self.call_puyu(prompt=prompt, history=history)

            elif remote_type == 'alles-apin':
                output_text = self.call_alles_apin(prompt=prompt,
                                                   history=history)
            else:
                logger.error('unknow backend {}'.format(remote_type))

        logger.info((self.remote_model, output_text))
        time_finish = time.time()

        logger.debug('Q:{} A:{} \t\t remote {} timecost {} '.format(
            prompt[-100:-1], output_text, self.remote_model,
            time_finish - time_tokenizer))
        return output_text


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Hybrid LLM Server.')
    parser.add_argument(
        '--config_path',
        default='config.ini',
        help=  # noqa E251
        'Hybrid LLM Server configuration path. Default value is config.ini'  # noqa E501
    )
    parser.add_argument('--unittest',
                        action='store_true',
                        default=False,
                        help='Test with samples.')
    args = parser.parse_args()
    return args


def llm_serve(config_path: str, server_ready: Value):
    """Start the LLM server.

    Args:
        config_path (str): Path to the configuration file.
        server_ready (multiprocessing.Value): Shared variable to indicate when the server is ready.  # noqa E501
    """
    # logger.add('logs/server.log', rotation="4MB")
    with open(config_path,'r', encoding='utf8') as f:
        llm_config = pytoml.load(f)['llm']
        bind_port = int(llm_config['server']['local_llm_bind_port'])

    try:
        server = HybridLLMServer(llm_config=llm_config,config_path=config_path)
        server_ready.value = 1
    except Exception as e:
        server_ready.value = -1
        raise (e)

    async def inference(request):
        """Call local llm inference."""

        input_json = await request.json()
        # logger.debug(input_json)

        prompt = input_json['prompt']
        history = input_json['history']
        backend = input_json['backend']
        # logger.debug(f'history: {history}')
        text = server.generate_response(prompt=prompt,
                                        history=history,
                                        backend=backend)
        return web.json_response({'text': text})

    app = web.Application()
    app.add_routes([web.post('/inference', inference)])
    web.run_app(app, host='0.0.0.0', port=bind_port)


def test_rpm():
    rpm = RPM(30)

    for i in range(40):
        rpm.wait()
        print(i)

    time.sleep(10)

    for i in range(40):
        rpm.wait()
        print(i)


def main():
    """Function to start the server without running a separate process."""
    args = parse_args()
    server_ready = Value('i', 0)

    if not args.unittest:
        llm_serve(args.config_path, server_ready)
    else:
        server_process = Process(target=llm_serve,
                                 args=(args.config_path, server_ready))
        server_process.daemon = True
        server_process.start()

        from .llm_client import ChatClient
        client = ChatClient(config_path=args.config_path)
        while server_ready.value == 0:
            logger.info('waiting for server to be ready..')
            time.sleep(2)

        queries = ['今天天气如何？']
        for query in queries:
            print(
                client.generate_response(prompt=query,
                                         history=[],
                                         backend='local'))


if __name__ == '__main__':
    main()
    # test_rpm()
