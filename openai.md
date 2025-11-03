
# openai connecotr #
## dcr server/unified server ##
- unified dcr 서버는 claude.ai와 같이. base URL의 root 에서 인증을 처리 한다. 
- base URL/enrollment 가 들어 오면 base URl로 리디렉트 해서 root 에서 모든 인증을 처리 한다. 

 ## connector/mcp server ##
 - Base URL : https://my-server.com/modules/v1/chat/completions 가 호출 됨으로  관련 도구를 래핑해서 처리 할 수 있도록 한다. 
 - v1/models는 정의하지 않는데  enrollment/v1/models, email/v1/models 등만 정의한다.
 - root 는 인증 만 하고 서브디렉토리 에서 mcp 서버가 구동한다. 
