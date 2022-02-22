#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <netdb.h>

#include <haproxy/blacklist.h>

struct Blacklist blacklist;

void SDSock_Make()
{
	int sock, i;
    struct hostent *he;
    struct in_addr **addr_list;
	struct sockaddr_in server;
	
	//Create socket
	sock = socket(AF_INET, SOCK_STREAM, 0);
	if (sock == -1)
	{
		printf("Could not create socket");
	}
	puts("Socket created.\n");
	
    // Determine ip from hostname
    char *hostname = "smartdrop";
    char ip[100];

    if ((he = gethostbyname(hostname)) == NULL)
    {
        herror("getbyhostname");
        return 1;
    }

    addr_list = (struct in_addr **) he->h_addr_list;

    for (i = 0; addr_list[i] != NULL; i++)
    {
        strcpy(ip, inet_ntoa(*addr_list[i]));
    }

	server.sin_addr.s_addr = inet_addr(ip);
	server.sin_family = AF_INET;
	server.sin_port = htons( 8080 );

	//Connect to remote server
	if (connect(sock, (struct sockaddr *)&server,
		sizeof(server)) < 0)
	{
		perror("connect failed. Error");
		return 1;
	}
	
	puts("Connected.\n");
	
	blacklist.sdsock = sock;

	return;
}
