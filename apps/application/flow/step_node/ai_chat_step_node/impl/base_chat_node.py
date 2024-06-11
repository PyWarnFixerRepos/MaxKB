# coding=utf-8
"""
    @project: maxkb
    @Author：虎
    @file： base_question_node.py
    @date：2024/6/4 14:30
    @desc:
"""
import json
from typing import List, Dict

from django.db.models import QuerySet
from langchain.schema import HumanMessage, SystemMessage
from langchain_core.messages import BaseMessage

from application.flow import tools
from application.flow.i_step_node import NodeResult, INode
from application.flow.step_node.ai_chat_step_node.i_chat_node import IChatNode
from common.util.rsa_util import rsa_long_decrypt
from setting.models import Model
from setting.models_provider.constants.model_provider_constants import ModelProvideConstants


def write_context_stream(node_variable: Dict, workflow_variable: Dict, node: INode, workflow):
    """
    写入上下文数据 (流式)
    @param node_variable:      节点数据
    @param workflow_variable:  全局数据
    @param node:               节点
    @param workflow:           工作流管理器
    """
    response = node_variable.get('result')
    answer = ''
    for chunk in response:
        answer += chunk.content
    chat_model = node_variable.get('chat_model')
    message_tokens = chat_model.get_num_tokens_from_messages(node_variable.get('message_list'))
    answer_tokens = chat_model.get_num_tokens(answer)
    node.context['message_tokens'] = message_tokens
    node.context['answer_tokens'] = answer_tokens
    node.context['answer'] = answer
    node.context['history_message'] = node_variable['history_message']
    node.context['question'] = node_variable['question']


def write_context(node_variable: Dict, workflow_variable: Dict, node: INode, workflow):
    """
    写入上下文数据
    @param node_variable:      节点数据
    @param workflow_variable:  全局数据
    @param node:               节点实例对象
    @param workflow:           工作流管理器
    """
    response = node_variable.get('result')
    chat_model = node_variable.get('chat_model')
    answer = response.content
    message_tokens = chat_model.get_num_tokens_from_messages(node_variable.get('message_list'))
    answer_tokens = chat_model.get_num_tokens(answer)
    node.context['message_tokens'] = message_tokens
    node.context['answer_tokens'] = answer_tokens
    node.context['answer'] = answer
    node.context['history_message'] = node_variable['history_message']
    node.context['question'] = node_variable['question']


def get_to_response_write_context(node_variable: Dict, node: INode):
    def _write_context(answer):
        chat_model = node_variable.get('chat_model')
        message_tokens = chat_model.get_num_tokens_from_messages(node_variable.get('message_list'))
        answer_tokens = chat_model.get_num_tokens(answer)
        node.context['message_tokens'] = message_tokens
        node.context['answer_tokens'] = answer_tokens
        node.context['answer'] = answer
        node.context['history_message'] = node_variable['history_message']
        node.context['question'] = node_variable['question']

    return _write_context


def to_stream_response(chat_id, chat_record_id, node_variable: Dict, workflow_variable: Dict, node, workflow,
                       post_handler):
    """
    将流式数据 转换为 流式响应
    @param chat_id:           会话id
    @param chat_record_id:    对话记录id
    @param node_variable:     节点数据
    @param workflow_variable: 工作流数据
    @param node:              节点
    @param workflow:          工作流管理器
    @param post_handler:      后置处理器 输出结果后执行
    @return: 流式响应
    """
    response = node_variable.get('result')
    _write_context = get_to_response_write_context(node_variable, node)
    return tools.to_stream_response(chat_id, chat_record_id, response, workflow, _write_context, post_handler)


def to_response(chat_id, chat_record_id, node_variable: Dict, workflow_variable: Dict, node, workflow,
                post_handler):
    """
    将结果转换
    @param chat_id:           会话id
    @param chat_record_id:    对话记录id
    @param node_variable:     节点数据
    @param workflow_variable: 工作流数据
    @param node:              节点
    @param workflow:          工作流管理器
    @param post_handler:      后置处理器
    @return: 响应
    """
    response = node_variable.get('result')
    _write_context = get_to_response_write_context(node_variable, node)
    return tools.to_response(chat_id, chat_record_id, response, workflow, _write_context, post_handler)


class BaseChatNode(IChatNode):
    def execute(self, model_id, system, prompt, dialogue_number, history_chat_record, stream, chat_id, chat_record_id,
                **kwargs) -> NodeResult:
        model = QuerySet(Model).filter(id=model_id).first()
        chat_model = ModelProvideConstants[model.provider].value.get_model(model.model_type, model.model_name,
                                                                           json.loads(
                                                                               rsa_long_decrypt(model.credential)),
                                                                           streaming=True)
        history_message = self.get_history_message(history_chat_record, dialogue_number)
        question = self.generate_prompt_question(prompt)
        message_list = self.generate_message_list(system, prompt, history_message)
        if stream:
            r = chat_model.stream(message_list)
            return NodeResult({'result': r, 'chat_model': chat_model, 'message_list': message_list,
                               'history_message': history_message, 'question': question}, {},
                              _write_context=write_context_stream,
                              _to_response=to_stream_response)
        else:
            r = chat_model.invoke(message_list)
            return NodeResult({'result': r, 'chat_model': chat_model, 'message_list': message_list,
                               'history_message': history_message, 'question': question}, {},
                              _write_context=write_context, _to_response=to_response)

    @staticmethod
    def get_history_message(history_chat_record, dialogue_number):
        start_index = len(history_chat_record) - dialogue_number
        history_message = [[history_chat_record[index].get_human_message(), history_chat_record[index].get_ai_message()]
                           for index in
                           range(start_index if start_index > 0 else 0, len(history_chat_record))]
        return history_message

    def generate_prompt_question(self, prompt):
        return HumanMessage(self.workflow_manage.generate_prompt(prompt))

    def generate_message_list(self, system: str, prompt: str, history_message):
        if system is None or len(system) == 0:
            return [SystemMessage(self.workflow_manage.generate_prompt(system)), *history_message,
                    HumanMessage(self.workflow_manage.generate_prompt(prompt))]
        else:
            return [*history_message, HumanMessage(self.workflow_manage.generate_prompt(prompt))]

    @staticmethod
    def reset_message_list(message_list: List[BaseMessage], answer_text):
        result = [{'role': 'user' if isinstance(message, HumanMessage) else 'ai', 'content': message.content} for
                  message
                  in
                  message_list]
        result.append({'role': 'ai', 'content': answer_text})
        return result

    def get_details(self, index: int, **kwargs):
        return {
            "index": index,
            'run_time': self.context.get('run_time'),
            'system': self.node_params.get('system'),
            'history_message': [{'content': message.content, 'role': message.type} for message in
                                self.context.get('history_message')],
            'question': self.context.get('question'),
            'answer': self.context.get('answer'),
            'type': self.node.type,
            'message_tokens': self.context['message_tokens'],
            'answer_tokens': self.context['answer_tokens']
        }
