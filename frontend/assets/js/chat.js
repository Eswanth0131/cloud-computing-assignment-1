/*
 * NYU Cloud Computing - Assignment 1
 * Dining Concierge Chatbot
 *
 * Frontend chat functionality
 * API Gateway integration
 * Session management
 */

(function () {
    "use strict";

    // --------------------------------------------------
    // Session Management
    // --------------------------------------------------

    var chatSessionId = sessionStorage.getItem("chatSessionId");

    if (!chatSessionId) {
        if (window.crypto && window.crypto.randomUUID) {
            chatSessionId = window.crypto.randomUUID();
        } else {
            chatSessionId =
                "session-" +
                Date.now() +
                "-" +
                Math.random().toString(36).substring(2);
        }

        sessionStorage.setItem("chatSessionId", chatSessionId);
    }

    // --------------------------------------------------
    // Application Initialization
    // --------------------------------------------------

    $(document).ready(function () {

        var $messages = $(".messages-content");
        var $input = $(".message-input");
        var $submit = $(".message-submit");

        var isSending = false;

        // Initialize custom scrollbar
        if ($.fn.mCustomScrollbar) {
            $messages.mCustomScrollbar();
        }

        // Initial greeting
        insertResponseMessage(
            "Hi there! I'm your personal Dining Concierge. " +
            "How can I help you today?"
        );

        // --------------------------------------------------
        // Scroll Management
        // --------------------------------------------------

        function updateScrollbar() {

            if ($.fn.mCustomScrollbar) {
                $messages
                    .mCustomScrollbar("update")
                    .mCustomScrollbar("scrollTo", "bottom", {
                        scrollInertia: 10,
                        timeout: 0
                    });
            } else {
                $messages.scrollTop(
                    $messages[0].scrollHeight
                );
            }
        }

        // --------------------------------------------------
        // Timestamp
        // --------------------------------------------------

        function setDate($message) {

            var date = new Date();

            var hours = date.getHours();
            var minutes = date.getMinutes();

            var formattedTime =
                String(hours).padStart(2, "0") +
                ":" +
                String(minutes).padStart(2, "0");

            $("<div></div>")
                .addClass("timestamp")
                .text(formattedTime)
                .appendTo($message);
        }

        // --------------------------------------------------
        // API Gateway Integration
        // --------------------------------------------------

        function callChatbotApi(message) {

            if (!window.CHATBOT_API_URL) {
                return Promise.reject(
                    new Error(
                        "API Gateway endpoint is not configured."
                    )
                );
            }

            var requestBody = {
                messages: [
                    {
                        type: "unstructured",
                        unstructured: {
                            id: chatSessionId,
                            text: message,
                            timestamp: new Date().toISOString()
                        }
                    }
                ]
            };

            return fetch(window.CHATBOT_API_URL, {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify(requestBody)
            })
            .then(function (response) {

                if (!response.ok) {
                    throw new Error(
                        "API request failed: " +
                        response.status
                    );
                }

                return response.json();
            });
        }

        // --------------------------------------------------
        // User Message
        // --------------------------------------------------

        function insertUserMessage(message) {

            var $message = $("<div></div>")
                .addClass("message message-personal new")
                .text(message);

            getMessageContainer().append($message);

            setDate($message);

            updateScrollbar();
        }

        // --------------------------------------------------
        // Bot Message
        // --------------------------------------------------

        function insertResponseMessage(content) {

            var $message = $("<div></div>")
                .addClass("message new");

            var $avatar = $("<figure></figure>")
                .addClass("avatar");

            var $image = $("<img>")
                .attr(
                    "src",
                    "https://media.tenor.com/images/4c347ea7198af12fd0a66790515f958f/tenor.gif"
                )
                .attr("alt", "Concierge");

            $avatar.append($image);

            $message.append($avatar);

            // Render as text to prevent HTML injection
            var $text = $("<span></span>")
                .text(content);

            $message.append($text);

            getMessageContainer().append($message);

            setDate($message);

            updateScrollbar();
        }

        // --------------------------------------------------
        // Message Container
        // --------------------------------------------------

        function getMessageContainer() {

            var $container = $messages.find(
                ".mCSB_container"
            );

            if ($container.length > 0) {
                return $container;
            }

            return $messages;
        }

        // --------------------------------------------------
        // Loading Indicator
        // --------------------------------------------------

        function showLoading() {

            var $loading = $("<div></div>")
                .addClass("message loading new")
                .attr("id", "chat-loading");

            var $avatar = $("<figure></figure>")
                .addClass("avatar");

            var $image = $("<img>")
                .attr(
                    "src",
                    "https://media.tenor.com/images/4c347ea7198af12fd0a66790515f958f/tenor.gif"
                );

            $avatar.append($image);

            $loading.append($avatar);

            $loading.append(
                $("<span></span>")
            );

            getMessageContainer().append($loading);

            updateScrollbar();
        }

        function hideLoading() {
            $("#chat-loading").remove();
        }

        // --------------------------------------------------
        // Process API Response
        // --------------------------------------------------

        function processBotResponse(data) {

            if (
                !data ||
                !Array.isArray(data.messages) ||
                data.messages.length === 0
            ) {

                insertResponseMessage(
                    "Sorry, I couldn't process your request."
                );

                return;
            }

            data.messages.forEach(function (message) {

                if (
                    message.type === "unstructured" &&
                    message.unstructured &&
                    typeof message.unstructured.text === "string"
                ) {

                    insertResponseMessage(
                        message.unstructured.text
                    );

                } else {

                    console.warn(
                        "Unsupported message format:",
                        message
                    );

                }
            });
        }

        // --------------------------------------------------
        // Send Message
        // --------------------------------------------------

        function insertMessage() {

            var message = $.trim($input.val());

            if (!message || isSending) {
                return;
            }

            isSending = true;

            $submit.prop("disabled", true);

            insertUserMessage(message);

            $input.val("");

            showLoading();

            callChatbotApi(message)

                .then(function (response) {

                    hideLoading();

                    processBotResponse(response);

                })

                .catch(function (error) {

                    hideLoading();

                    console.error(
                        "Chatbot API error:",
                        error
                    );

                    insertResponseMessage(
                        "Sorry, something went wrong. " +
                        "Please try again."
                    );

                })

                .finally(function () {

                    isSending = false;

                    $submit.prop("disabled", false);

                    $input.focus();

                });
        }

        // --------------------------------------------------
        // Event Listeners
        // --------------------------------------------------

        // Send button
        $submit.on("click", function () {
            insertMessage();
        });

        // Enter sends message
        $input.on("keydown", function (event) {

            if (
                event.which === 13 &&
                !event.shiftKey
            ) {

                event.preventDefault();

                insertMessage();
            }
        });

    });

})();