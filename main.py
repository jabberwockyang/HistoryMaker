import json
from loguru import logger
import os
import json
import time
from multiprocessing import Process, Value

from loguru import logger
from HistoryMaker.worker import HISTORY_WORKER
from HistoryMaker.llm_server_hybrid import llm_serve


def start_server():
    server_ready = Value('i', 0)
    server_process = Process(target=llm_serve,
                            args=(CONFIG_PATH, server_ready))
    server_process.start()
    while True:
        if server_ready.value == 0:
            logger.info('waiting for server to be ready..')
            time.sleep(3)
        elif server_ready.value == 1:
            break
        else:
            logger.error('start local LLM server failed, quit.')
            raise Exception('local LLM path')
    logger.info('Hybrid LLM Server start.')

def main(input, output):
    # hybrid llm serve
    start_server()
    with open (input, 'r') as f:
        lines = f.readlines()
    jsonlist = [json.loads(line) for line in lines]

    if os.path.exists(output):
        with open(output, 'r') as f:
            lines = f.readlines()
        processed_jsonlist = [json.loads(line) for line in lines]
        ppdlist = [item['dialog'] for item in processed_jsonlist]
    else:
        ppdlist = []

    jsonlist = [item for item in jsonlist if item['dialog'] not in ppdlist]
    logger.info(f"already processed: {len(ppdlist)}, left to process: {len(jsonlist)}")

    assistant = HISTORY_WORKER(config_path=CONFIG_PATH,language='zh')

    for item in jsonlist:
        dialog = item['dialog']
        extracted = assistant.generate_history(dialog)
        item['extracted'] = extracted
        modified = assistant.modify_history(extracted)
        item['modified'] = modified
        text = assistant.generate_text(modified)
        item['extracted_paste'] = text
        logger.info(f"extracted success: {extracted}")
        with open(output, 'a') as f:
            f.write(json.dumps(item,ensure_ascii=False)+'\n')

def check(input, output):
    with open (input, 'r') as f:
        lines = f.readlines()
    jsonlist = [json.loads(line) for line in lines]
    def add_hu(item):
        item['hu_checked'] = item['modified']
        return item
    jsonlist = [add_hu(item) for item in jsonlist]
    with open(output, 'w') as f:
        json.dump(jsonlist, f, ensure_ascii=False, indent=4)


def refresh(input, output):
    with open(input, 'r') as f:
        jsonlist = json.load(f)
    assistant = HISTORY_WORKER(config_path=CONFIG_PATH,language='zh')
    def refresh_item(item,assistant):
        newitem = {}
        newitem['question'] = item['question']
        newitem['options'] = item['options']
        newitem['other'] = item['other']
        newitem['answer'] = assistant.generate_text(item['hu_checked'])
        return newitem
    
    jsonlist = [refresh_item(item,assistant) for item in jsonlist]
    with open(output, 'w') as f:
        for item in jsonlist:
            f.write(json.dumps(item,ensure_ascii=False)+'\n')

if __name__ == '__main__':
    
    CONFIG_PATH = 'config.ini'

    input = 'IMCS-V2-MRG_test.jsonl'
    output = 'IMCS-V2-MRG_response.jsonl'
    main(input, output)

    # input =  'IMCS-V2-MRG_response.jsonl'
    # output = 'IMCS-V2-MRG_check.json'
    # check(input,output)

    # input = 'IMCS-V2-MRG_check.json'
    # output = 'IMCS-V2-MRG_final.jsonl'
    # refresh(input,output)

